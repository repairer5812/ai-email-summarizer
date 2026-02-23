from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

from webmail_summary.export.obsidian.exporter import (
    MessageExportInput,
    export_daily_note,
    export_email_note,
)
from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import (
    list_messages_for_resummarize_by_date,
    list_messages_for_resummarize_by_ids,
    set_analysis,
)
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.text_sanitize import sanitize_text_for_llm


def _parse_date_key(date_key: str) -> dt.date:
    dk = (date_key or "").strip()
    try:
        return dt.date.fromisoformat(dk)
    except Exception:
        raise RuntimeError("invalid date_key")


def _needs_resummarize(summary: str) -> bool:
    s = (summary or "").strip().lower()
    if not s:
        return True
    if "llm unavailable" in s:
        return True
    if "failed to format input" in s or "invalid codepoint" in s:
        return True
    if "loading model" in s or "available commands" in s:
        return True
    # If the summary is actually JSON-ish, treat as bad.
    if s.startswith("{") or s.startswith("```json") or s.startswith("```"):
        return True
    return False


def resummarize_day_task(
    *,
    date_key: str,
    only_failed: bool = True,
    message_ids: list[int] | None = None,
):
    def run(job_id: str, cancel: threading.Event) -> None:
        data_dir = get_app_data_dir()
        db_path = data_dir / "db.sqlite3"

        # Validate date
        day = _parse_date_key(date_key)

        conn = get_conn(db_path)
        try:
            s = load_settings(conn)
        finally:
            conn.close()

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

        connpi = get_conn(db_path)
        try:
            repo.add_event(
                connpi,
                job_id=job_id,
                level="info",
                text=f"llm_provider={provider.__class__.__name__}",
            )
        finally:
            connpi.close()

        vault_root = (
            Path(s.obsidian_root) if s.obsidian_root else default_obsidian_root()
        )
        vault_root.mkdir(parents=True, exist_ok=True)

        conn0 = get_conn(db_path)
        try:
            if message_ids:
                rows = list_messages_for_resummarize_by_ids(
                    conn0, message_ids=list(message_ids)
                )
            else:
                rows = list_messages_for_resummarize_by_date(
                    conn0, date_prefix=day.isoformat()
                )
        finally:
            conn0.close()

        if message_ids:
            # User-selected messages: always resummarize exactly those.
            targets = rows
        else:
            if only_failed:
                # r[8] is the stored summary text.
                targets = [r for r in rows if _needs_resummarize(str(r[8] or ""))]
            else:
                targets = rows

        connp = get_conn(db_path)
        try:
            repo.update_progress(
                connp,
                job_id=job_id,
                current=0,
                total=max(len(targets), 1),
                message=f"[{day.isoformat()}] 날짜별 다시 요약 준비 중",
            )
            repo.add_event(
                connp,
                job_id=job_id,
                level="info",
                text=f"resummarize day={day.isoformat()} targets={len(targets)}",
            )
        finally:
            connp.close()

        processed_notes: list[Path] = []

        if not targets:
            connz = get_conn(db_path)
            try:
                repo.update_progress(
                    connz,
                    job_id=job_id,
                    current=1,
                    total=1,
                    message=f"[{day.isoformat()}] 다시 요약할 항목 없음",
                )
                repo.add_event(connz, job_id=job_id, level="info", text="no targets")
            finally:
                connz.close()
            return

        for i, r in enumerate(targets, start=1):
            if cancel.is_set():
                break

            msg_id = int(r[0])
            account_id = str(r[1] or "")
            uidvalidity = int(r[3] or 0)
            uid = int(r[4] or 0)
            subject = str(r[5] or "(no subject)")
            from_addr = str(r[6] or s.sender_filter or "")
            internal_date = str(r[7] or "")
            raw_eml_path = str(r[9] or "")
            body_text_path = str(r[10] or "")
            body_html_path = str(r[11] or "")

            display_date = internal_date[:10]
            display_sub = (subject[:30] + "...") if len(subject) > 30 else subject

            connx = get_conn(db_path)
            try:
                repo.update_progress(
                    connx,
                    job_id=job_id,
                    current=i - 0.99,
                    total=max(len(targets), 1),
                    message=f"[{display_date}] 다시 요약 중: {display_sub} ({i}/{len(targets)})",
                )

                repo.add_event(
                    connx,
                    job_id=job_id,
                    level="info",
                    text=f"item {i}/{len(targets)}: {subject}",
                )
                repo.add_event(
                    connx,
                    job_id=job_id,
                    level="detail",
                    text=json.dumps(
                        {
                            "type": "email",
                            "message_id": msg_id,
                            "index": i,
                            "total": len(targets),
                            "subject": subject,
                        },
                        ensure_ascii=True,
                    ),
                )
                repo.add_event(
                    connx,
                    job_id=job_id,
                    level="detail",
                    text=json.dumps(
                        {"type": "stage", "stage": "read"}, ensure_ascii=True
                    ),
                )
            finally:
                connx.close()

            body_text = ""
            p_txt = Path(body_text_path) if body_text_path else None
            p_html = Path(body_html_path) if body_html_path else None
            if p_txt and p_txt.exists():
                body_text = p_txt.read_text(encoding="utf-8", errors="replace")
            elif p_html and p_html.exists():
                from bs4 import BeautifulSoup

                raw_html = p_html.read_text(encoding="utf-8", errors="replace")
                body_text = BeautifulSoup(raw_html, "html.parser").get_text("\n")

            connw = get_conn(db_path)
            try:
                repo.update_progress(
                    connw,
                    job_id=job_id,
                    current=i - 0.95,  # Start with a small offset instead of 100%
                    total=max(len(targets), 1),
                    message=f"[{display_date}] LLM 호출 중: {display_sub} ({i}/{len(targets)})",
                )
                repo.add_event(
                    connw,
                    job_id=job_id,
                    level="detail",
                    text=json.dumps(
                        {"type": "stage", "stage": "llm"}, ensure_ascii=True
                    ),
                )
            finally:
                connw.close()

            def emit_detail(d: dict) -> None:
                conn_d = get_conn(db_path)
                try:
                    repo.add_event(
                        conn_d,
                        job_id=job_id,
                        level="detail",
                        text=json.dumps(d, ensure_ascii=True),
                    )
                finally:
                    conn_d.close()

            def update_sub_progress(fraction: float) -> None:
                # fraction is 0.0 to 1.0 within the current email.
                # Total progress = (i - 1 + fraction) / total
                conn_p = get_conn(db_path)
                try:
                    repo.update_progress(
                        conn_p,
                        job_id=job_id,
                        current=i - 1 + fraction,
                        total=max(len(targets), 1),
                        message=f"[{display_date}] 다시 요약 중: {display_sub} ({i}/{len(targets)})",
                    )
                finally:
                    conn_p.close()

            t0 = time.monotonic()

            # Rate limit for cloud providers (Gemini free tier etc.)
            if provider.__class__.__name__ == "CloudProvider":
                time.sleep(2)

            user_profile = {"roles": s.user_roles, "interests": s.user_interests}
            llm_res = summarize_email_long_aware(
                provider,
                subject=sanitize_text_for_llm(subject),
                body=sanitize_text_for_llm(body_text),
                on_detail=emit_detail,
                on_progress=update_sub_progress,
                user_profile=user_profile,
            )

            dt_s = time.monotonic() - t0
            topics = llm_res.backlinks

            connw3 = get_conn(db_path)
            try:
                repo.add_event(
                    connw3,
                    job_id=job_id,
                    level="detail",
                    text=json.dumps(
                        {"type": "stage", "stage": "save"}, ensure_ascii=True
                    ),
                )
            finally:
                connw3.close()

            connw2 = get_conn(db_path)
            try:
                if dt_s > 60:
                    repo.add_event(
                        connw2,
                        job_id=job_id,
                        level="warn",
                        text=f"LLM 느림: {dt_s:.1f}s (item {i}/{len(targets)})",
                    )
                else:
                    repo.add_event(
                        connw2,
                        job_id=job_id,
                        level="info",
                        text=f"LLM 완료: {dt_s:.1f}s (item {i}/{len(targets)})",
                    )
            finally:
                connw2.close()

            connu = get_conn(db_path)
            try:
                set_analysis(
                    connu,
                    message_fk=msg_id,
                    summary=llm_res.summary,
                    tags=llm_res.tags,
                    topics=topics,
                    personal=llm_res.personal,
                    summarize_ms=int(max(0.0, dt_s) * 1000.0),
                )
                connu.commit()
            finally:
                connu.close()

            conne = get_conn(db_path)
            try:
                repo.add_event(
                    conne,
                    job_id=job_id,
                    level="message_updated",
                    text=json.dumps(
                        {"message_id": msg_id, "summary": llm_res.summary},
                        ensure_ascii=True,
                    ),
                )
            finally:
                conne.close()

            # Re-export email note (idempotent overwrite).
            connw4 = get_conn(db_path)
            try:
                repo.add_event(
                    connw4,
                    job_id=job_id,
                    level="detail",
                    text=json.dumps(
                        {"type": "stage", "stage": "export"}, ensure_ascii=True
                    ),
                )
            finally:
                connw4.close()
            try:
                archive_dir = Path(raw_eml_path).parent if raw_eml_path else data_dir
                try:
                    email_dt = dt.datetime.fromisoformat(internal_date).date()
                except Exception:
                    email_dt = day

                note_path = export_email_note(
                    vault_root=vault_root,
                    inp=MessageExportInput(
                        message_key=f"{account_id}-{uidvalidity}-{uid}",
                        date=email_dt,
                        sender=from_addr,
                        subject=subject,
                        summary=llm_res.summary,
                        tags=llm_res.tags,
                        topics=topics,
                        archive_dir=archive_dir,
                    ),
                )
                processed_notes.append(note_path)
            except Exception:
                # Export failures should not stop resummarize.
                continue

        connf = get_conn(db_path)
        try:
            repo.update_progress(
                connf,
                job_id=job_id,
                current=len(targets),
                total=max(len(targets), 1),
                message=f"[{day.isoformat()}] 다시 요약 완료",
            )
        finally:
            connf.close()

        # Rebuild daily note for the date (best-effort).
        try:
            if processed_notes:
                daily_summary = "\n".join([f"- {p.stem}" for p in processed_notes])
                export_daily_note(
                    vault_root=vault_root,
                    date=day,
                    message_notes=processed_notes,
                    daily_summary=daily_summary,
                )

            # Synthesize Daily Overview for Dashboard
            from webmail_summary.index.mail_repo import (
                list_messages_by_date,
                set_daily_overview,
            )
            from webmail_summary.llm.long_summarize import synthesize_daily_overview

            connd = get_conn(db_path)
            try:
                msg_rows = list_messages_by_date(connd, date_prefix=day.isoformat())
                all_sums = [str(r["summary"] or "") for r in msg_rows if r["summary"]]
                if all_sums:
                    user_profile = {
                        "roles": s.user_roles,
                        "interests": s.user_interests,
                    }
                    ov = synthesize_daily_overview(
                        provider,
                        day=day.isoformat(),
                        summaries=all_sums,
                        user_profile=user_profile,
                    )
                    if ov:
                        set_daily_overview(connd, day=day.isoformat(), overview=ov)
                        connd.commit()
            finally:
                connd.close()
        except Exception:
            pass

    return run
