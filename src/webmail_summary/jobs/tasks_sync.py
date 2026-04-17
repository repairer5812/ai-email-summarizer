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
from PIL import Image

from webmail_summary.archive.paths import get_message_paths
from webmail_summary.archive.pipeline import archive_message
from webmail_summary.archive.html_rewrite import ExternalAsset
from webmail_summary.archive.mime_parts import SavedAttachment
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
    get_incomplete_uids,
    replace_attachments,
    replace_external_assets,
    set_analysis,
    set_exported,
    set_seen_marked,
    upsert_message,
)
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_for_dates
from webmail_summary.llm.base import LlmImageInput, LlmResult
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.text_sanitize import (
    html_to_visible_text,
    prepare_body_for_llm,
    sanitize_text_for_llm,
)


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


def _cloud_base_delay_seconds(cloud_provider: str, model: str) -> float:
    provider = str(cloud_provider or "").strip().lower()
    model_name = str(model or "").strip().lower()

    if provider in {"openai", "anthropic", "openrouter"}:
        return 0.3
    if provider in {"google", "upstage"}:
        return 0.5
    if "gemini" in model_name:
        return 0.5
    return 0.4


def _display_subject(subject: str, *, max_len: int = 30) -> str:
    s = str(subject or "")
    return (s[:max_len] + "...") if len(s) > max_len else s


def _stage_label(stage: str) -> str:
    stage_map = {
        "archive": "백업 중",
        "index": "저장 중",
        "summarize": "요약 중",
        "export": "Obsidian 내보내기 중",
        "mark": "읽음 처리 중",
    }
    return stage_map.get(stage, stage)


def _build_stage_message(*, stage: str, display_date: str, subject: str) -> str:
    return f"[{display_date}] {_stage_label(stage)}: {_display_subject(subject)}"


def _add_job_event(*, db_path: Path, job_id: str, level: str, text: str) -> None:
    conn = get_conn(db_path)
    try:
        repo.add_event(conn, job_id=job_id, level=level, text=text)
    finally:
        conn.close()


def _update_job_progress(
    *, db_path: Path, job_id: str, current: float, total: float, message: str
) -> None:
    conn = get_conn(db_path)
    try:
        repo.update_progress(
            conn,
            job_id=job_id,
            current=current,
            total=total,
            message=message,
        )
    finally:
        conn.close()


def _load_body_text_for_llm(
    *, body_text_path: str | None, body_html_path: str | None
) -> str:
    body_text = ""
    if body_text_path and Path(body_text_path).exists():
        body_text = Path(body_text_path).read_text(encoding="utf-8", errors="replace")
    elif body_html_path and Path(body_html_path).exists():
        raw_html = Path(body_html_path).read_text(encoding="utf-8", errors="replace")
        body_text = html_to_visible_text(raw_html)
    return prepare_body_for_llm(body_text)


def _llm_timeout_seconds(provider) -> float:
    tier = getattr(provider, "tier", "standard")
    if tier == "cloud":
        return 420.0
    if tier == "fast":
        return 240.0
    return 360.0


_SUPPORTED_MM_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MIN_MM_IMAGE_BYTES = 1024


def _is_supported_mm_image(*, path: Path, mime_type: str | None) -> bool:
    mime = str(mime_type or "").strip().lower()
    if mime.startswith("image/") and mime not in {"image/svg+xml"}:
        return True
    return path.suffix.lower() in _SUPPORTED_MM_EXTS


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            w, h = img.size
            return int(w), int(h)
    except Exception:
        return None


def _should_exclude_mm_image(
    *,
    path: Path,
    mime_type: str | None,
    source: str,
    dims: tuple[int, int] | None,
) -> bool:
    name = path.name.lower()
    if any(k in name for k in ["logo", "icon", "favicon", "avatar", "sprite", "badge"]):
        return True

    if dims:
        width, height = dims
        if width <= 220 or height <= 120:
            return True
        if width >= 600 and height <= 140:
            return True
        if height > 0:
            aspect = width / height
            if width >= 600 and aspect >= 5.5 and height <= 180:
                return True
            if source == "inline_attachment" and aspect >= 4.0 and height <= 160:
                return True

    mime = str(mime_type or "").strip().lower()
    if mime == "image/gif" and dims and dims[1] <= 180:
        return True

    return False


def _select_multimodal_inputs(
    *,
    base_dir: Path,
    attachments: list[SavedAttachment],
    external_assets: list[ExternalAsset],
    max_images: int = 3,
    max_total_bytes: int = 4 * 1024 * 1024,
) -> list[LlmImageInput]:
    wide_candidates: list[tuple[int, Path, str | None, str]] = []
    candidates: list[tuple[int, Path, str | None, str]] = []

    for a in attachments or []:
        p = (base_dir / str(a.rel_path or "")).resolve()
        if not p.is_file() or not _is_supported_mm_image(path=p, mime_type=a.mime_type):
            continue
        size = int(a.size_bytes or 0)
        source = "inline_attachment" if bool(a.is_inline) else "attachment"
        dims = _image_dimensions(p)
        if _should_exclude_mm_image(
            path=p, mime_type=a.mime_type, source=source, dims=dims
        ):
            continue
        item = (size, p, a.mime_type, source)
        if dims and dims[0] > 600:
            wide_candidates.append(item)
        else:
            if size <= _MIN_MM_IMAGE_BYTES:
                continue
            candidates.append(item)

    for a in external_assets or []:
        if str(a.status or "").strip().lower() != "downloaded":
            continue
        rel = str(a.rel_path or "").strip()
        if not rel:
            continue
        p = (base_dir / rel).resolve()
        if not p.is_file() or not _is_supported_mm_image(path=p, mime_type=a.mime_type):
            continue
        size = int(a.size_bytes or (p.stat().st_size if p.exists() else 0) or 0)
        dims = _image_dimensions(p)
        if _should_exclude_mm_image(
            path=p,
            mime_type=a.mime_type,
            source="external_asset",
            dims=dims,
        ):
            continue
        item = (size, p, a.mime_type, "external_asset")
        if dims and dims[0] > 600:
            wide_candidates.append(item)
        else:
            if size <= _MIN_MM_IMAGE_BYTES:
                continue
            candidates.append(item)

    wide_candidates.sort(key=lambda x: x[0], reverse=True)
    candidates.sort(key=lambda x: x[0], reverse=True)
    out: list[LlmImageInput] = []
    seen: set[str] = set()

    for _size, p, mime, source in wide_candidates:
        rp = str(p)
        if rp in seen:
            continue
        out.append(LlmImageInput(path=rp, mime_type=mime, detail="low", source=source))
        seen.add(rp)

    total = sum(p.stat().st_size for p in [Path(x.path) for x in out] if p.exists())

    for size, p, mime, source in candidates:
        rp = str(p)
        if rp in seen:
            continue
        if len(out) >= int(max_images):
            break
        if total + int(size) > int(max_total_bytes):
            continue
        out.append(LlmImageInput(path=rp, mime_type=mime, detail="low", source=source))
        seen.add(rp)
        total += int(size)
    return out


def _run_llm_summary(
    *,
    db_path: Path,
    job_id: str,
    provider,
    subject: str,
    body_text: str,
    user_profile: dict,
    update_sub_progress,
    item_index: int,
    item_total: int,
    display_date: str,
    display_sub: str,
    multimodal_inputs: list[LlmImageInput] | None,
) -> LlmResult:
    llm_done = threading.Event()

    def _llm_heartbeat() -> None:
        start_ts = time.monotonic()
        while not llm_done.wait(5.0):
            elapsed = time.monotonic() - start_ts
            mm = int(elapsed // 60)
            ss = int(elapsed % 60)
            conn_hb = get_conn(db_path)
            try:
                cur_job = repo.get_job(conn_hb, job_id)
                cur_progress = item_index - 0.99
                if cur_job is not None:
                    try:
                        cur_progress = max(
                            float(cur_progress),
                            float(cur_job.progress_current or 0),
                        )
                    except Exception:
                        cur_progress = item_index - 0.99
                repo.update_progress(
                    conn_hb,
                    job_id=job_id,
                    current=cur_progress,
                    total=max(item_total, 1),
                    message=(
                        f"[{display_date}] 요약 중: {display_sub} ({item_index}/{item_total}) "
                        f"(경과 {mm:02d}:{ss:02d})"
                    ),
                )
            finally:
                conn_hb.close()

    hb_t = threading.Thread(target=_llm_heartbeat, daemon=True)
    hb_t.start()
    llm_result_box: dict[str, LlmResult] = {}
    llm_err_box: dict[str, Exception] = {}

    def _run_llm_call() -> None:
        try:
            llm_result_box["res"] = summarize_email_long_aware(
                provider,
                subject=sanitize_text_for_llm(str(subject)),
                body=sanitize_text_for_llm(body_text),
                on_progress=update_sub_progress,
                user_profile=user_profile,
                multimodal_inputs=multimodal_inputs,
            )
        except Exception as ex:
            llm_err_box["err"] = ex
        finally:
            llm_done.set()

    llm_t = threading.Thread(target=_run_llm_call, daemon=True)
    llm_t.start()

    llm_timeout_s = _llm_timeout_seconds(provider)
    if not llm_done.wait(llm_timeout_s):
        _add_job_event(
            db_path=db_path,
            job_id=job_id,
            level="warn",
            text=f"LLM timeout: {llm_timeout_s:.0f}s (item {item_index}/{item_total})",
        )

        llm_done.set()
        try:
            hb_t.join(timeout=1.0)
        except Exception:
            pass

        try:
            stop_done = threading.Event()

            def _stop_local_server() -> None:
                try:
                    from webmail_summary.llm.llamacpp_server import stop_server

                    stop_server(force=True)
                finally:
                    stop_done.set()

            threading.Thread(target=_stop_local_server, daemon=True).start()
            stop_done.wait(2.5)
        except Exception:
            pass

        try:
            llm_t.join(timeout=0.2)
        except Exception:
            pass

        return LlmResult(
            summary="(LLM timeout)",
            tags=[],
            backlinks=[],
            personal=False,
        )

    llm_res = llm_result_box.get("res")
    if llm_res is None:
        if "err" in llm_err_box:
            _add_job_event(
                db_path=db_path,
                job_id=job_id,
                level="warn",
                text=f"LLM exception: {str(llm_err_box['err'])[:180]}",
            )
        llm_res = LlmResult(
            summary="(LLM unavailable)",
            tags=[],
            backlinks=[],
            personal=False,
        )

    llm_done.set()
    try:
        hb_t.join(timeout=1.0)
    except Exception:
        pass
    return llm_res


def _group_processed_notes(
    processed_notes: list[tuple[str, Path, list[str]]],
) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    by_date: dict[str, list[Path]] = {}
    by_topic: dict[str, list[Path]] = {}
    for d, note, topics in processed_notes:
        by_date.setdefault(d, []).append(note)
        for t in topics:
            by_topic.setdefault(t, []).append(note)
    return by_date, by_topic


def _build_daily_summary(notes: list[Path]) -> str:
    return "\n".join([f"- {p.stem}" for p in notes])


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
                # Collect UIDs that were archived but failed mid-pipeline
                # (summarize/export/mark-seen). These must be retried.
                retry_uids = get_incomplete_uids(
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
            new_uids = imap.search_uids(
                s.sender_filter,
                since,
                unseen_only=False,
                min_uid_exclusive=last_uid,
            )
            # Merge: retry incomplete UIDs first, then new ones.
            retry_set = set(retry_uids)
            uids = retry_uids + [u for u in new_uids if u not in retry_set]

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

            msg_total = int(len(uids))

            def _on_fetch_progress(fetched: int, total: int) -> None:
                if cancel.is_set():
                    return
                # Keep the UI alive while fetching large batches.
                _update_job_progress(
                    db_path=db_path,
                    job_id=job_id,
                    current=0,
                    total=max(msg_total, 1),
                    message=f"메일 가져오는 중 ({int(fetched)}/{max(int(total), 1)})",
                )

            msg_iter = imap.iter_messages(
                uids, chunk_size=20, on_progress=_on_fetch_progress
            )
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
                for i, m in enumerate(msg_iter, start=1):
                    if cancel.is_set():
                        break

                    # Extract basic info early for progress reporting
                    hdr = _parse_headers(m.rfc822)
                    internal_date_str = _email_date(m.internaldate)
                    subject = hdr.get("subject") or "(no subject)"
                    display_date = internal_date_str[:10]
                    display_sub = _display_subject(subject)

                    def set_stage(stage: str) -> None:
                        _update_job_progress(
                            db_path=db_path,
                            job_id=job_id,
                            current=i - 0.99,
                            total=max(msg_total, 1),
                            message=_build_stage_message(
                                stage=stage,
                                display_date=display_date,
                                subject=subject,
                            ),
                        )

                    set_stage("archive")

                    _add_job_event(
                        db_path=db_path,
                        job_id=job_id,
                        level="info",
                        text="아카이브 시작",
                    )

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
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="warn",
                            text=f"아카이브가 느립니다 ({dt_s:.1f}초)",
                        )

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

                    body_text = _load_body_text_for_llm(
                        body_text_path=str(ar.body_text_path)
                        if ar.body_text_path
                        else None,
                        body_html_path=str(ar.body_html_path)
                        if ar.body_html_path
                        else None,
                    )
                    multimodal_inputs: list[LlmImageInput] | None = None
                    if provider.supports_multimodal_inputs() and bool(
                        getattr(s, "cloud_multimodal_enabled", False)
                    ):
                        selected_inputs = _select_multimodal_inputs(
                            base_dir=paths.base_dir,
                            attachments=list(ar.attachments or []),
                            external_assets=list(ar.external_assets or []),
                        )
                        if selected_inputs:
                            multimodal_inputs = selected_inputs

                    set_stage("summarize")
                    _add_job_event(
                        db_path=db_path,
                        job_id=job_id,
                        level="info",
                        text="요약 시작",
                    )

                    def update_sub_progress(fraction: float) -> None:
                        _update_job_progress(
                            db_path=db_path,
                            job_id=job_id,
                            current=i - 1 + fraction,
                            total=max(msg_total, 1),
                            message=f"[{display_date}] 요약 중: {display_sub} ({i}/{msg_total})",
                        )

                    t1 = time.monotonic()

                    # Cloud pacing: keep a small provider-specific delay.
                    if provider.__class__.__name__ == "CloudProvider":
                        time.sleep(
                            _cloud_base_delay_seconds(
                                s.cloud_provider,
                                s.openrouter_model,
                            )
                        )

                    user_profile = {
                        "roles": s.user_roles,
                        "interests": s.user_interests,
                    }

                    llm_res = _run_llm_summary(
                        db_path=db_path,
                        job_id=job_id,
                        provider=provider,
                        subject=subject,
                        body_text=body_text,
                        user_profile=user_profile,
                        update_sub_progress=update_sub_progress,
                        item_index=i,
                        item_total=msg_total,
                        display_date=display_date,
                        display_sub=display_sub,
                        multimodal_inputs=multimodal_inputs,
                    )

                    topics = llm_res.backlinks

                    dt2_s = time.monotonic() - t1
                    if dt2_s > 60:
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="warn",
                            text=f"요약이 느립니다 ({dt2_s:.1f}초)",
                        )

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
                    note_path: Path | None = None
                    try:
                        note_path = export_email_note(
                            vault_root=vault_root,
                            inp=MessageExportInput(
                                message_key=f"{account_id}-{uidvalidity}-{m.uid}",
                                date=email_dt,
                                sender=str(hdr.get("from") or "(unknown)"),
                                subject=str(subject),
                                summary=llm_res.summary,
                                tags=llm_res.tags,
                                topics=topics,
                                archive_dir=paths.base_dir,
                            ),
                        )
                    except Exception as e:
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="error",
                            text=f"Obsidian export failed (continuing): {e}",
                        )
                        _update_job_progress(
                            db_path=db_path,
                            job_id=job_id,
                            current=i,
                            total=max(msg_total, 1),
                            message=f"[{display_date}] Obsidian 내보내기 실패 (계속): {display_sub} ({i}/{msg_total})",
                        )
                        continue

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
                    if note_path is not None:
                        processed_notes.append((date_prefix, note_path, topics))

                # Daily digests + topic notes
                by_date, by_topic = _group_processed_notes(processed_notes)

                for d, notes in by_date.items():
                    daily_summary = _build_daily_summary(notes)
                    try:
                        export_daily_note(
                            vault_root=vault_root,
                            date=datetime.fromisoformat(d).date(),
                            message_notes=notes,
                            daily_summary=daily_summary,
                        )
                    except Exception as e:
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="warn",
                            text=f"Obsidian daily export failed: {e}",
                        )

                for t, notes in by_topic.items():
                    try:
                        export_topic_note(
                            vault_root=vault_root, topic=t, message_notes=notes
                        )
                    except Exception as e:
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="warn",
                            text=f"Obsidian topic export failed: {e}",
                        )

                if by_date:
                    try:
                        refreshed_days = refresh_overviews_for_dates(
                            db_path=db_path,
                            provider=provider,
                            settings=s,
                            date_keys=list(by_date.keys()),
                            force_refresh=True,
                            job_id=job_id,
                        )
                        if refreshed_days:
                            _add_job_event(
                                db_path=db_path,
                                job_id=job_id,
                                level="info",
                                text="daily_overview refreshed: "
                                + ", ".join(refreshed_days),
                            )
                    except Exception as e:
                        _add_job_event(
                            db_path=db_path,
                            job_id=job_id,
                            level="warn",
                            text=f"daily_overview refresh failed: {e}",
                        )

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
