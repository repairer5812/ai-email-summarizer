from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from datetime import timedelta

try:
    from zoneinfo import ZoneInfo

    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = timezone(timedelta(hours=9))
from email import policy
from email.parser import BytesParser
from pathlib import Path

import keyring

from webmail_summary.archive.paths import get_message_paths
from webmail_summary.archive.pipeline import archive_message
from webmail_summary.export.obsidian.exporter import (
    MessageExportInput,
    export_daily_note,
    export_email_note,
    export_topic_note,
)
from webmail_summary.imap_client import ImapSession
from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import (
    get_max_uid,
    replace_attachments,
    replace_external_assets,
    set_analysis,
    set_exported,
    set_seen_marked,
    upsert_message,
)
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.text_sanitize import sanitize_text_for_llm


def _account_id(user: str, host: str) -> str:
    return f"{user}@{host}"


def _parse_headers(raw: bytes) -> dict[str, str | None]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    return {
        "message_id": msg.get("Message-ID"),
        "date": msg.get("Date"),
        "from": msg.get("From"),
        "to": msg.get("To"),
        "subject": msg.get("Subject"),
    }


def _email_date(internal_date: datetime | None) -> str:
    if internal_date is None:
        return datetime.now(_KST).isoformat()
    if internal_date.tzinfo is None:
        return internal_date.replace(tzinfo=_KST).isoformat()
    return internal_date.astimezone(_KST).isoformat()


def sync_mailbox_task() -> Callable[[str, threading.Event], None]:
    def run(job_id: str, cancel: threading.Event) -> None:
        data_dir = get_app_data_dir()
        db_path = data_dir / "db.sqlite3"

        conn = get_conn(db_path)
        try:
            s = load_settings(conn)
        finally:
            conn.close()

        if not s.imap_host or not s.imap_user:
            raise RuntimeError("not configured")

        account_id = _account_id(s.imap_user, s.imap_host)

        service = f"webmail-summary::{s.imap_host}"
        pw = keyring.get_password(service, s.imap_user)
        if not pw:
            raise RuntimeError("password not stored")

        try:
            provider = get_llm_provider(s)
        except LlmNotReady as e:
            connr = get_conn(db_path)
            try:
                repo.add_event(connr, job_id=job_id, level="error", text=str(e))
                repo.set_job_status(
                    connr, job_id=job_id, status="failed", message=str(e)
                )
            finally:
                connr.close()
            raise

        vault_root = (
            Path(s.obsidian_root) if s.obsidian_root else default_obsidian_root()
        )
        vault_root.mkdir(parents=True, exist_ok=True)

        revert_seen = bool(getattr(s, "revert_seen_after_sync", False))
        to_revert: list[int] = []

        with ImapSession(s.imap_host, s.imap_port, s.imap_user, pw) as imap:
            # Fetch uses BODY.PEEK[] (see ImapSession.fetch_messages) to avoid implicit \Seen changes.
            imap.select_folder(s.imap_folder, readonly=False)
            uidvalidity = imap.get_uidvalidity_for(s.imap_folder)

            conn0 = get_conn(db_path)
            try:
                last_uid = get_max_uid(
                    conn0,
                    account_id=account_id,
                    mailbox=s.imap_folder,
                    uidvalidity=uidvalidity,
                )
            finally:
                conn0.close()

            # Sync the last 60 days, then filter by UID watermark.
            import datetime as dt

            since = dt.date.today() - dt.timedelta(days=60)
            uids = imap.search_uids(
                s.sender_filter,
                since,
                unseen_only=False,
                min_uid_exclusive=last_uid,
            )

            connp = get_conn(db_path)
            try:
                repo.update_progress(
                    connp,
                    job_id=job_id,
                    current=0,
                    total=max(len(uids), 1),
                    message="동기화 준비 중",
                )
            finally:
                connp.close()

            msgs = imap.fetch_messages(uids)
            processed_notes: list[
                tuple[str, Path, list[str]]
            ] = []  # date_prefix, note_path, topics

            def _mark_seen_retry(uid: int) -> None:
                try:
                    imap.mark_seen(uid)
                    return
                except Exception:
                    pass
                # Reconnect once for transient socket/SSL errors.
                with ImapSession(s.imap_host, s.imap_port, s.imap_user, pw) as im2:
                    im2.select_folder(s.imap_folder, readonly=False)
                    im2.mark_seen(uid)

            def _clear_seen_retry(uid: int) -> None:
                try:
                    imap.clear_seen(uid)
                    return
                except Exception:
                    pass
                with ImapSession(s.imap_host, s.imap_port, s.imap_user, pw) as im2:
                    im2.select_folder(s.imap_folder, readonly=False)
                    im2.clear_seen(uid)

            try:
                for i, m in enumerate(msgs, start=1):
                    if cancel.is_set():
                        break

                    # Extract basic info early for progress reporting
                    hdr = _parse_headers(m.rfc822)
                    internal_date_str = _email_date(m.internaldate)
                    subject = hdr.get("subject") or "(no subject)"
                    # Short date for display: YYYY-MM-DD
                    display_date = internal_date_str[:10]
                    # Short subject for display
                    display_sub = (
                        (subject[:30] + "...") if len(subject) > 30 else subject
                    )

                    def set_stage(stage: str) -> None:
                        stage_map = {
                            "archive": "백업 중",
                            "index": "저장 중",
                            "summarize": "요약 중",
                            "export": "Obsidian 내보내기 중",
                            "mark": "읽음 처리 중",
                        }
                        stage_name = stage_map.get(stage, stage)
                        msg = f"[{display_date}] {stage_name}: {display_sub}"
                        connx = get_conn(db_path)
                        try:
                            repo.update_progress(
                                connx,
                                job_id=job_id,
                                current=i - 0.99,
                                total=max(len(msgs), 1),
                                message=msg,
                            )
                        finally:
                            connx.close()

                    set_stage("archive")

                    connl = get_conn(db_path)
                    try:
                        repo.add_event(
                            connl,
                            job_id=job_id,
                            level="info",
                            text="아카이브 시작",
                        )
                    finally:
                        connl.close()

                    t0 = time.monotonic()

                    paths = get_message_paths(
                        data_root=data_dir,
                        account_id=account_id,
                        mailbox=s.imap_folder,
                        uidvalidity=uidvalidity,
                        uid=m.uid,
                    )
                    ar = archive_message(
                        raw_rfc822=m.rfc822,
                        paths=paths,
                        external_max_bytes=s.external_max_bytes,
                    )

                    dt_s = time.monotonic() - t0
                    if dt_s > 15:
                        connl2 = get_conn(db_path)
                        try:
                            repo.add_event(
                                connl2,
                                job_id=job_id,
                                level="warn",
                                text=f"아카이브가 느립니다 ({dt_s:.1f}초)",
                            )
                        finally:
                            connl2.close()

                    set_stage("index")
                    conn1 = get_conn(db_path)
                    try:
                        msg_fk = upsert_message(
                            conn1,
                            account_id=account_id,
                            mailbox=s.imap_folder,
                            uidvalidity=uidvalidity,
                            uid=m.uid,
                            message_id=hdr.get("message_id"),
                            internal_date=internal_date_str,
                            from_addr=hdr.get("from"),
                            to_addr=hdr.get("to"),
                            subject=subject,
                            raw_eml_path=str(ar.raw_eml_path),
                            body_html_path=str(ar.body_html_path)
                            if ar.body_html_path
                            else None,
                            body_text_path=str(ar.body_text_path)
                            if ar.body_text_path
                            else None,
                            rendered_html_path=str(ar.rendered_html_path)
                            if ar.rendered_html_path
                            else None,
                        )
                        replace_attachments(
                            conn1,
                            message_fk=msg_fk,
                            items=[
                                {
                                    "filename": a.filename,
                                    "mime_type": a.mime_type,
                                    "size_bytes": a.size_bytes,
                                    "rel_path": a.rel_path,
                                    "content_id": a.content_id,
                                    "is_inline": a.is_inline,
                                }
                                for a in ar.attachments
                            ],
                        )
                        replace_external_assets(
                            conn1,
                            message_fk=msg_fk,
                            items=[
                                {
                                    "original_url": a.original_url,
                                    "rel_path": a.rel_path,
                                    "mime_type": a.mime_type,
                                    "size_bytes": a.size_bytes,
                                    "status": a.status,
                                }
                                for a in ar.external_assets
                            ],
                        )
                        conn1.commit()
                    finally:
                        conn1.close()

                    body_text = ""
                    if ar.body_text_path and Path(ar.body_text_path).exists():
                        body_text = Path(ar.body_text_path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                    elif ar.body_html_path and Path(ar.body_html_path).exists():
                        # fallback: strip html
                        from bs4 import BeautifulSoup

                        raw_html = Path(ar.body_html_path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                        body_text = BeautifulSoup(raw_html, "html.parser").get_text(
                            "\n"
                        )

                    set_stage("summarize")
                    connl3 = get_conn(db_path)
                    try:
                        repo.add_event(
                            connl3,
                            job_id=job_id,
                            level="info",
                            text="요약 시작",
                        )
                    finally:
                        connl3.close()

                    def update_sub_progress(fraction: float) -> None:
                        # fraction 0.0-1.0 within the email.
                        conn_p = get_conn(db_path)
                        try:
                            repo.update_progress(
                                conn_p,
                                job_id=job_id,
                                current=i - 1 + fraction,
                                total=max(len(msgs), 1),
                                message=f"[{display_date}] 요약 중: {display_sub} ({i}/{len(msgs)})",
                            )
                        finally:
                            conn_p.close()

                    t1 = time.monotonic()

                    # Rate limit for cloud providers
                    if provider.__class__.__name__ == "CloudProvider":
                        time.sleep(2)

                    user_profile = {
                        "roles": s.user_roles,
                        "interests": s.user_interests,
                    }
                    llm_res = summarize_email_long_aware(
                        provider,
                        subject=sanitize_text_for_llm(str(subject)),
                        body=sanitize_text_for_llm(body_text),
                        on_progress=update_sub_progress,
                        user_profile=user_profile,
                    )

                    topics = llm_res.backlinks

                    dt2_s = time.monotonic() - t1
                    if dt2_s > 60:
                        connl4 = get_conn(db_path)
                        try:
                            repo.add_event(
                                connl4,
                                job_id=job_id,
                                level="warn",
                                text=f"요약이 느립니다 ({dt2_s:.1f}초)",
                            )
                        finally:
                            connl4.close()

                    conn2 = get_conn(db_path)
                    try:
                        set_analysis(
                            conn2,
                            message_fk=msg_fk,
                            summary=llm_res.summary,
                            tags=llm_res.tags,
                            topics=topics,
                            personal=llm_res.personal,
                            summarize_ms=int(max(0.0, dt2_s) * 1000.0),
                        )
                        conn2.commit()
                    finally:
                        conn2.close()

                    # Export to Obsidian
                    set_stage("export")
                    email_dt = (
                        m.internaldate.date() if m.internaldate else dt.date.today()
                    )
                    note_path = export_email_note(
                        vault_root=vault_root,
                        inp=MessageExportInput(
                            message_key=f"{account_id}-{uidvalidity}-{m.uid}",
                            date=email_dt,
                            sender=str(hdr.get("from") or s.sender_filter),
                            subject=str(subject),
                            summary=llm_res.summary,
                            tags=llm_res.tags,
                            topics=topics,
                            archive_dir=paths.base_dir,
                        ),
                    )

                    conn3 = get_conn(db_path)
                    try:
                        set_exported(conn3, message_fk=msg_fk)
                        conn3.commit()
                    finally:
                        conn3.close()

                    # Mark as read only after durable export
                    set_stage("mark")
                    originally_seen = any(
                        (f.lower() == b"\\seen") for f in (m.flags or tuple())
                    )

                    try:
                        _mark_seen_retry(m.uid)
                        if revert_seen and not originally_seen:
                            to_revert.append(int(m.uid))
                        connm = get_conn(db_path)
                        try:
                            set_seen_marked(connm, message_fk=msg_fk)
                            connm.commit()
                        finally:
                            connm.close()
                    except Exception as e:
                        connm2 = get_conn(db_path)
                        try:
                            repo.add_event(
                                connm2,
                                job_id=job_id,
                                level="warn",
                                text=f"읽음 처리 실패: {e}",
                            )
                        finally:
                            connm2.close()

                    # Collect for daily/topic notes
                    date_prefix = (
                        m.internaldate.date().isoformat()
                        if m.internaldate
                        else dt.date.today().isoformat()
                    )
                    processed_notes.append((date_prefix, note_path, topics))

                # Daily digests + topic notes
                by_date: dict[str, list[Path]] = {}
                by_topic: dict[str, list[Path]] = {}
                for d, note, topics in processed_notes:
                    by_date.setdefault(d, []).append(note)
                    for t in topics:
                        by_topic.setdefault(t, []).append(note)

                for d, notes in by_date.items():
                    # Simple daily summary: list subjects.
                    daily_summary = "\n".join([f"- {p.stem}" for p in notes])
                    export_daily_note(
                        vault_root=vault_root,
                        date=datetime.fromisoformat(d).date(),
                        message_notes=notes,
                        daily_summary=daily_summary,
                    )

                for t, notes in by_topic.items():
                    export_topic_note(
                        vault_root=vault_root, topic=t, message_notes=notes
                    )

                # Daily Overviews synthesis
                from webmail_summary.index.mail_repo import (
                    get_daily_overview,
                    list_messages_by_date,
                    set_daily_overview,
                )
                from webmail_summary.llm.long_summarize import synthesize_daily_overview

                for d in by_date.keys():
                    conn_d = get_conn(db_path)
                    try:
                        # Fetch all summaries for this date to synthesize
                        msg_rows = list_messages_by_date(conn_d, date_prefix=d)
                        all_sums = [
                            str(r["summary"] or "") for r in msg_rows if r["summary"]
                        ]
                        if all_sums:
                            user_profile = {
                                "roles": s.user_roles,
                                "interests": s.user_interests,
                            }
                            overview = synthesize_daily_overview(
                                provider,
                                day=d,
                                summaries=all_sums,
                                user_profile=user_profile,
                            )
                            if overview:
                                set_daily_overview(conn_d, day=d, overview=overview)
                                conn_d.commit()
                    finally:
                        conn_d.close()
            finally:
                if revert_seen and to_revert:
                    # Best-effort revert for smoke tests.
                    for uid in to_revert:
                        try:
                            _clear_seen_retry(int(uid))
                        except Exception as e:
                            connw = get_conn(db_path)
                            try:
                                repo.add_event(
                                    connw,
                                    job_id=job_id,
                                    level="warn",
                                    text=f"안읽음 원복 실패: {e}",
                                )
                            finally:
                                connw.close()

    return run
