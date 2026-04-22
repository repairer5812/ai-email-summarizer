from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

from webmail_summary.export.obsidian.exporter import (
    MessageExportInput,
    email_note_filename,
    export_daily_note,
    export_email_note,
    export_topic_note,
)
from webmail_summary.export.obsidian.naming import safe_topic_name
from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import (
    get_message_ids_by_topic,
    list_messages_for_resummarize_by_date,
    list_messages_for_resummarize_by_dates,
    list_messages_for_resummarize_by_ids,
    set_analysis,
)
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_for_dates
from webmail_summary.llm.base import LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
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


def _normalize_date_keys(
    *, date_key: str = "", date_keys: list[str] | None = None
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    raw = [date_key, *(date_keys or [])]
    for item in raw:
        day = str(item or "").strip()
        if not day or day in seen:
            continue
        _parse_date_key(day)
        seen.add(day)
        out.append(day)
    return out


def _needs_resummarize(summary: str) -> bool:
    s = (summary or "").strip().lower()
    if not s:
        return True
    compact = "".join(ch for ch in s if ch.isalnum() or ("\uac00" <= ch <= "\ud7a3"))
    if "nosummary" in compact or "?붿빟?놁쓬" in compact:
        return True
    if "?곸꽭?붿빟??ぉ?대?議깊빀?덈떎" in compact:
        return True
    if "\uc694\uc57d\ud56d\ubaa9\uc774\ubd80\uc871\ud569\ub2c8\ub2e4" in compact:
        return True
    if "llm timeout" in s or "(llm timeout)" in s:
        return True
    if "llm unavailable" in s:
        return True
    if "failed to format input" in s or "invalid codepoint" in s:
        return True
    if "loading model" in s or "available commands" in s:
        return True
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
    date_key: str = "",
    date_keys: list[str] | None = None,
    only_failed: bool = True,
    message_ids: list[int] | None = None,
):
    def run(job_id: str, cancel: threading.Event) -> None:
        class _ResummarizeCancelled(Exception):
            pass

        data_dir = get_app_data_dir()
        db_path = data_dir / "db.sqlite3"

        day_keys = _normalize_date_keys(date_key=date_key, date_keys=date_keys)
        if not day_keys:
            raise RuntimeError("date_key required")
        if message_ids and len(day_keys) != 1:
            raise RuntimeError("message_ids require exactly one date")

        single_day_key = day_keys[0] if len(day_keys) == 1 else ""
        single_day = _parse_date_key(single_day_key) if single_day_key else None
        is_multi_day = len(day_keys) > 1

        def _scope_message(*, single: str, multi: str) -> str:
            return single if not is_multi_day else multi

        def _item_message(
            display_date: str,
            display_sub: str,
            index: int,
            total: int,
            *,
            llm: bool = False,
            elapsed: str = "",
        ) -> str:
            if is_multi_day:
                stage = "선택 날짜 LLM 호출 중" if llm else "선택 날짜 다시 요약 중"
                base = f"{stage} {display_date} / {display_sub} ({index}/{total})"
            else:
                stage = "LLM 호출 중" if llm else "다시 요약 중"
                base = f"[{display_date}] {stage} {display_sub} ({index}/{total})"
            if elapsed:
                return f"{base} {elapsed}"
            return base

        conn = get_conn(db_path)
        try:
            settings = load_settings(conn)
        finally:
            conn.close()

        try:
            provider = get_llm_provider(settings)
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
            Path(settings.obsidian_root)
            if settings.obsidian_root
            else default_obsidian_root()
        )
        vault_root.mkdir(parents=True, exist_ok=True)

        conn0 = get_conn(db_path)
        try:
            if message_ids:
                rows = list_messages_for_resummarize_by_ids(
                    conn0, message_ids=list(message_ids)
                )
            elif len(day_keys) == 1:
                rows = list_messages_for_resummarize_by_date(
                    conn0, date_prefix=day_keys[0]
                )
            else:
                rows = list_messages_for_resummarize_by_dates(
                    conn0, date_keys=list(day_keys)
                )
        finally:
            conn0.close()

        if message_ids:
            targets = rows
        elif only_failed:
            targets = [r for r in rows if _needs_resummarize(str(r[8] or ""))]
        else:
            targets = rows

        prepare_message = _scope_message(
            single=f"[{single_day_key}] 날짜별 다시 요약 준비 중",
            multi=(
                f"선택 날짜 {len(day_keys)}일 "
                + ("오류만 다시 요약 준비 중" if only_failed else "전체 다시 요약 준비 중")
            ),
        )
        empty_message = _scope_message(
            single=f"[{single_day_key}] 다시 요약 대상 없음",
            multi=(
                "선택 날짜에 오류 요약 대상이 없습니다"
                if only_failed
                else "선택 날짜에 다시 요약할 대상이 없습니다"
            ),
        )
        cancelled_message = _scope_message(
            single=f"[{single_day_key}] 다시 요약 취소됨",
            multi="선택 날짜 다시 요약 취소됨",
        )
        completed_message = _scope_message(
            single=f"[{single_day_key}] 다시 요약 완료",
            multi="선택 날짜 다시 요약 완료",
        )

        connp = get_conn(db_path)
        try:
            repo.update_progress(
                connp,
                job_id=job_id,
                current=0,
                total=max(len(targets), 1),
                message=prepare_message,
            )
            repo.add_event(
                connp,
                job_id=job_id,
                level="info",
                text=f"resummarize days={','.join(day_keys)} targets={len(targets)}",
            )
        finally:
            connp.close()

        processed_notes_by_day: dict[str, list[Path]] = {}
        touched_day_keys: set[str] = set()
        all_topics: dict[str, list[Path]] = {}
        processed_count = 0

        if not targets:
            connz = get_conn(db_path)
            try:
                repo.update_progress(
                    connz,
                    job_id=job_id,
                    current=1,
                    total=1,
                    message=empty_message,
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
            from_addr = str(r[6] or settings.sender_filter or "")
            internal_date = str(r[7] or "")
            raw_eml_path = str(r[9] or "")
            body_text_path = str(r[10] or "")
            body_html_path = str(r[11] or "")

            old_topics: list[str] = []
            try:
                old_topics = json.loads(str(r[12] or "[]")) or []
            except Exception:
                old_topics = []

            display_date = internal_date[:10] if len(internal_date) >= 10 else single_day_key
            display_sub = (subject[:30] + "...") if len(subject) > 30 else subject

            connx = get_conn(db_path)
            try:
                repo.update_progress(
                    connx,
                    job_id=job_id,
                    current=i - 0.99,
                    total=max(len(targets), 1),
                    message=_item_message(
                        display_date,
                        display_sub,
                        i,
                        len(targets),
                    ),
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
                    current=i - 0.95,
                    total=max(len(targets), 1),
                    message=_item_message(
                        display_date,
                        display_sub,
                        i,
                        len(targets),
                        llm=True,
                    ),
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

            frac_lock = threading.Lock()
            last_fraction = 0.0

            def _set_fraction(v: float) -> None:
                nonlocal last_fraction
                with frac_lock:
                    try:
                        vv = float(v)
                    except Exception:
                        return
                    vv = max(0.0, min(1.0, vv))
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
                conn_p = get_conn(db_path)
                try:
                    repo.update_progress(
                        conn_p,
                        job_id=job_id,
                        current=i - 1 + fraction,
                        total=max(len(targets), 1),
                        message=_item_message(
                            display_date,
                            display_sub,
                            i,
                            len(targets),
                        ),
                    )
                finally:
                    conn_p.close()

            t0 = time.monotonic()
            if provider.__class__.__name__ == "CloudProvider":
                time.sleep(
                    _cloud_base_delay_seconds(
                        settings.cloud_provider,
                        settings.openrouter_model,
                    )
                )

            user_profile = {
                "roles": settings.user_roles,
                "interests": settings.user_interests,
            }
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
                            message=_item_message(
                                display_date,
                                display_sub,
                                i,
                                len(targets),
                                llm=True,
                                elapsed=f"(경과 {mm:02d}:{ss:02d})",
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
                        text=f"LLM 경고: {dt_s:.1f}s (item {i}/{len(targets)})",
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

            if display_date:
                touched_day_keys.add(display_date)
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
                    email_dt = single_day or _parse_date_key(day_keys[0])

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
                processed_notes_by_day.setdefault(display_date, []).append(note_path)
                for t in topics:
                    all_topics.setdefault(t, []).append(note_path)
                for t in old_topics:
                    if t not in all_topics:
                        all_topics[t] = []
            except Exception:
                continue

        if cancel.is_set():
            connc = get_conn(db_path)
            try:
                repo.update_progress(
                    connc,
                    job_id=job_id,
                    current=float(processed_count),
                    total=max(len(targets), 1),
                    message=cancelled_message,
                )
                repo.add_event(connc, job_id=job_id, level="info", text="cancelled")
            finally:
                connc.close()
            return

        try:
            for day_key, processed_notes in processed_notes_by_day.items():
                if not processed_notes:
                    continue
                daily_summary = "\n".join(f"- {p.stem}" for p in processed_notes)
                export_daily_note(
                    vault_root=vault_root,
                    date=_parse_date_key(day_key),
                    message_notes=processed_notes,
                    daily_summary=daily_summary,
                )

            if touched_day_keys:
                refresh_overviews_for_dates(
                    db_path=db_path,
                    provider=provider,
                    settings=settings,
                    date_keys=sorted(touched_day_keys),
                    force_refresh=True,
                    job_id=job_id,
                )

            for topic in all_topics:
                try:
                    conn_topic = get_conn(db_path)
                    try:
                        remaining = get_message_ids_by_topic(conn_topic, topic=topic)
                    finally:
                        conn_topic.close()

                    if not remaining:
                        topic_file = vault_root / "Topic" / f"{safe_topic_name(topic)}.md"
                        if topic_file.exists():
                            topic_file.unlink(missing_ok=True)
                        continue

                    topic_notes: list[Path] = []
                    conn_notes = get_conn(db_path)
                    try:
                        for mid in remaining:
                            row = conn_notes.execute(
                                "SELECT account_id, uidvalidity, uid, subject, internal_date "
                                "FROM messages WHERE id=?",
                                (mid,),
                            ).fetchone()
                            if not row:
                                continue
                            m_account = str(row[0] or "")
                            m_uidv = int(row[1] or 0)
                            m_uid = int(row[2] or 0)
                            m_subj = str(row[3] or "(no subject)")
                            m_date_s = str(row[4] or "")
                            try:
                                m_date = dt.datetime.fromisoformat(m_date_s).date()
                            except Exception:
                                m_date = dt.date.today()
                            m_key = f"{m_account}-{m_uidv}-{m_uid}"
                            fname = email_note_filename(m_date, m_subj, m_key)
                            note_path = vault_root / "Mail" / f"{m_date:%Y-%m}" / fname
                            if note_path.exists():
                                topic_notes.append(note_path)
                    finally:
                        conn_notes.close()

                    export_topic_note(
                        vault_root=vault_root,
                        topic=topic,
                        message_notes=topic_notes,
                        replace=True,
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
                message=completed_message,
            )
        finally:
            connf.close()

    return run
