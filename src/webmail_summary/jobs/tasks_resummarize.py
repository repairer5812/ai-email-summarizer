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
    export_topic_note,
)
from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import (
    list_messages_for_resummarize_by_date,
    list_messages_for_resummarize_by_ids,
    set_analysis,
)
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_for_dates
from webmail_summary.llm.base import LlmResult
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.text_sanitize import (
    html_to_visible_text,
    prepare_body_for_llm,
    sanitize_text_for_llm,
)


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
    if "llm timeout" in s or "(llm timeout)" in s:
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


def resummarize_day_task(
    *,
    date_key: str,
    only_failed: bool = True,
    message_ids: list[int] | None = None,
):
    def run(job_id: str, cancel: threading.Event) -> None:
        class _ResummarizeCancelled(Exception):
            pass

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
        all_topics: dict[str, list[Path]] = {}  # topic -> note paths

        processed_count = 0

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
                raw_html = p_html.read_text(encoding="utf-8", errors="replace")
                body_text = html_to_visible_text(raw_html)

            body_text = prepare_body_for_llm(body_text)

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

            # Heartbeat: if the provider does not call on_progress for a while,
            # keep updating the job message with elapsed time so the UI doesn't
            # look stuck.
            frac_lock = threading.Lock()
            last_fraction = 0.0

            def _set_fraction(v: float) -> None:
                nonlocal last_fraction
                with frac_lock:
                    try:
                        vv = float(v)
                    except Exception:
                        return
                    if vv < 0.0:
                        vv = 0.0
                    if vv > 1.0:
                        vv = 1.0
                    if vv > last_fraction:
                        last_fraction = vv

            def emit_detail(d: dict) -> None:
                if cancel.is_set():
                    raise _ResummarizeCancelled()
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
                if cancel.is_set():
                    raise _ResummarizeCancelled()
                _set_fraction(fraction)
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

            # Cloud pacing: keep a small provider-specific delay.
            if provider.__class__.__name__ == "CloudProvider":
                time.sleep(
                    _cloud_base_delay_seconds(
                        s.cloud_provider,
                        s.openrouter_model,
                    )
                )

            user_profile = {"roles": s.user_roles, "interests": s.user_interests}
            llm_done = threading.Event()
            llm_result_box: dict[str, LlmResult] = {}
            llm_err_box: dict[str, Exception] = {}

            def _run_llm_call() -> None:
                try:
                    llm_result_box["res"] = summarize_email_long_aware(
                        provider,
                        subject=sanitize_text_for_llm(subject),
                        body=sanitize_text_for_llm(body_text),
                        on_detail=emit_detail,
                        on_progress=update_sub_progress,
                        user_profile=user_profile,
                    )
                except _ResummarizeCancelled as ex:
                    llm_err_box["err"] = ex
                except Exception as ex:
                    llm_err_box["err"] = ex
                finally:
                    llm_done.set()

            llm_t = threading.Thread(target=_run_llm_call, daemon=True)
            llm_t.start()

            hb_stop = threading.Event()

            def _llm_heartbeat() -> None:
                started = time.monotonic()
                # Update at a low frequency to avoid DB spam.
                while (
                    not hb_stop.is_set()
                    and not llm_done.is_set()
                    and not cancel.is_set()
                ):
                    time.sleep(2.0)
                    if hb_stop.is_set() or llm_done.is_set() or cancel.is_set():
                        break
                    dt_s = max(0.0, time.monotonic() - started)
                    mm = int(dt_s // 60)
                    ss = int(dt_s % 60)
                    with frac_lock:
                        frac = float(last_fraction)
                    cur = max(i - 0.95, (i - 1) + frac)
                    conn_hb = get_conn(db_path)
                    try:
                        repo.update_progress(
                            conn_hb,
                            job_id=job_id,
                            current=cur,
                            total=max(len(targets), 1),
                            message=(
                                f"[{display_date}] LLM 호출 중: {display_sub} ({i}/{len(targets)}) "
                                f"(경과 {mm:02d}:{ss:02d})"
                            ),
                        )
                    finally:
                        conn_hb.close()

            hb_t = threading.Thread(target=_llm_heartbeat, daemon=True)
            hb_t.start()

            tier = getattr(provider, "tier", "standard")
            if tier == "cloud":
                llm_timeout_s = 420.0
            elif tier == "fast":
                llm_timeout_s = 240.0
            else:
                llm_timeout_s = 360.0
            if not llm_done.wait(llm_timeout_s):
                hb_stop.set()
                try:
                    hb_t.join(timeout=1.0)
                except Exception:
                    pass
                conn_to = get_conn(db_path)
                try:
                    repo.add_event(
                        conn_to,
                        job_id=job_id,
                        level="warn",
                        text=f"LLM timeout: {llm_timeout_s:.0f}s (item {i}/{len(targets)})",
                    )
                finally:
                    conn_to.close()
                llm_done.set()
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
                llm_res = LlmResult(
                    summary="(LLM timeout)", tags=[], backlinks=[], personal=False
                )
            else:
                hb_stop.set()
                try:
                    hb_t.join(timeout=1.0)
                except Exception:
                    pass
                llm_res = llm_result_box.get("res")
                if llm_res is None:
                    if "err" in llm_err_box:
                        if isinstance(llm_err_box["err"], _ResummarizeCancelled):
                            cancel.set()
                            break
                        conn_er = get_conn(db_path)
                        try:
                            repo.add_event(
                                conn_er,
                                job_id=job_id,
                                level="warn",
                                text=f"LLM exception: {str(llm_err_box['err'])[:180]}",
                            )
                        finally:
                            conn_er.close()
                    llm_res = LlmResult(
                        summary="(LLM unavailable)",
                        tags=[],
                        backlinks=[],
                        personal=False,
                    )
                try:
                    llm_t.join(timeout=0.2)
                except Exception:
                    pass

            if cancel.is_set() or isinstance(
                llm_err_box.get("err"), _ResummarizeCancelled
            ):
                cancel.set()
                break

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

            processed_count = i

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
                for t in topics:
                    all_topics.setdefault(t, []).append(note_path)
            except Exception:
                # Export failures should not stop resummarize.
                continue

        if cancel.is_set():
            connc = get_conn(db_path)
            try:
                repo.update_progress(
                    connc,
                    job_id=job_id,
                    current=float(processed_count),
                    total=max(len(targets), 1),
                    message=f"[{day.isoformat()}] 다시 요약 취소됨",
                )
                repo.add_event(connc, job_id=job_id, level="info", text="cancelled")
            finally:
                connc.close()
            return

        # Rebuild daily note and daily overview for the date (best-effort).
        try:
            if processed_notes:
                daily_summary = "\n".join([f"- {p.stem}" for p in processed_notes])
                export_daily_note(
                    vault_root=vault_root,
                    date=day,
                    message_notes=processed_notes,
                    daily_summary=daily_summary,
                )

            refresh_overviews_for_dates(
                db_path=db_path,
                provider=provider,
                settings=s,
                date_keys=[day.isoformat()],
                force_refresh=True,
                job_id=job_id,
            )

            # Rebuild topic notes for all topics referenced by re-summarized messages.
            for t, notes in all_topics.items():
                try:
                    export_topic_note(
                        vault_root=vault_root, topic=t, message_notes=notes
                    )
                except Exception:
                    pass
        except Exception:
            pass

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

    return run
