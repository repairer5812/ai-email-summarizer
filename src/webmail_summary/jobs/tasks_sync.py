from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

import keyring

from webmail_summary.archive.paths import get_message_paths
from webmail_summary.util.timefmt import KST as _KST
from webmail_summary.archive.pipeline import archive_message
from webmail_summary.export.obsidian.exporter import (
    MessageExportInput,
    export_daily_note,
    export_email_note,
    export_topic_note,
)
from webmail_summary.imap_client import ImapSession
from webmail_summary.index.db import app_db_path, open_db
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
from webmail_summary.jobs.llm_call import (
    Heartbeat,
    call_with_deadline,
    cloud_base_delay_seconds,
    fallback_result,
    format_elapsed,
    llm_timeout_seconds,
    select_multimodal_inputs,
    wants_multimodal_inputs,
)
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


def _cloud_chunk_size(cloud_provider: str, model: str) -> int:
    """Concurrent LLM call count per chunk, tuned to provider rate limits.

    Low-RPM tiers (Google Gemini Flash free 15 RPM, Upstage Solar 30 RPM,
    OpenRouter free models often 20 RPM) get a small chunk_size=2 to avoid
    429 herd. Paid tiers (OpenAI 500+ RPM, Anthropic 50+ RPM tier 1) use
    chunk_size=5. OpenRouter is provider-agnostic so we use a moderate
    chunk_size=3.
    """
    provider = str(cloud_provider or "").strip().lower()
    model_name = str(model or "").strip().lower()

    if provider in {"google", "upstage"}:
        return 2
    if "flash" in model_name or ":free" in model_name or "/free" in model_name:
        return 2
    if provider in {"openai", "anthropic"}:
        return 5
    if provider == "openrouter":
        return 3
    return 3


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
    with open_db(db_path) as conn:
        repo.add_event(conn, job_id=job_id, level=level, text=text)


def _update_job_progress(
    *, db_path: Path, job_id: str, current: float, total: float, message: str
) -> None:
    with open_db(db_path) as conn:
        repo.update_progress(
            conn,
            job_id=job_id,
            current=current,
            total=total,
            message=message,
        )


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
    def _heartbeat_tick(elapsed_s: float) -> None:
        with open_db(db_path) as conn_hb:
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
                    f"(경과 {format_elapsed(elapsed_s)})"
                ),
            )

    llm_timeout_s = llm_timeout_seconds(provider)

    def _log_timeout() -> None:
        _add_job_event(
            db_path=db_path,
            job_id=job_id,
            level="warn",
            text=f"LLM timeout: {llm_timeout_s:.0f}s (item {item_index}/{item_total})",
        )

    outcome = call_with_deadline(
        lambda: summarize_email_long_aware(
            provider,
            subject=sanitize_text_for_llm(str(subject)),
            body=sanitize_text_for_llm(body_text),
            on_progress=update_sub_progress,
            user_profile=user_profile,
            multimodal_inputs=multimodal_inputs,
        ),
        timeout_s=llm_timeout_s,
        heartbeat=Heartbeat(_heartbeat_tick),
        on_timeout=_log_timeout,
    )
    if outcome.timed_out:
        return fallback_result("(LLM timeout)")
    if outcome.result is not None:
        return outcome.result
    if outcome.error is not None:
        _add_job_event(
            db_path=db_path,
            job_id=job_id,
            level="warn",
            text=f"LLM exception: {str(outcome.error)[:180]}",
        )
    return fallback_result("(LLM unavailable)")


def _chunked(iterable: Iterable, n: int) -> Iterator[list]:
    """Yield chunks of size n from iterable. Last chunk may be smaller."""
    chunk: list = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= n:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


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
        db_path = app_db_path(data_dir)

        with open_db(db_path) as conn:
            s = load_settings(conn)

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
            with open_db(db_path) as connr:
                repo.add_event(connr, job_id=job_id, level="error", text=str(e))
                repo.set_job_status(
                    connr, job_id=job_id, status="failed", message=str(e)
                )
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

            with open_db(db_path) as conn0:
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

            with open_db(db_path) as connp:
                repo.update_progress(
                    connp,
                    job_id=job_id,
                    current=0,
                    total=max(len(uids), 1),
                    message="동기화 준비 중",
                )

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

            # Chunked + concurrent LLM calls for CloudProvider; serial for
            # local. chunk_size is provider-rate-limit aware: free/low-RPM
            # tiers get 2, paid tiers get 3-5.
            if provider.__class__.__name__ == "CloudProvider":
                chunk_size = _cloud_chunk_size(
                    s.cloud_provider, s.openrouter_model
                )
            else:
                chunk_size = 1

            def _set_stage_for(
                *, i_global: int, display_date: str, subject: str, stage: str
            ) -> None:
                _update_job_progress(
                    db_path=db_path,
                    job_id=job_id,
                    current=i_global - 0.99,
                    total=max(msg_total, 1),
                    message=_build_stage_message(
                        stage=stage,
                        display_date=display_date,
                        subject=subject,
                    ),
                )

            def _archive_and_index_one(i_global: int, m):
                """Archive + DB upsert + body/multimodal prep. Serial per mail."""
                hdr = _parse_headers(m.rfc822)
                internal_date_str = _email_date(m.internaldate)
                subject = hdr.get("subject") or "(no subject)"
                display_date = internal_date_str[:10]
                display_sub = _display_subject(subject)

                _set_stage_for(
                    i_global=i_global,
                    display_date=display_date,
                    subject=subject,
                    stage="archive",
                )
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

                _set_stage_for(
                    i_global=i_global,
                    display_date=display_date,
                    subject=subject,
                    stage="index",
                )
                with open_db(db_path) as conn1:
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

                body_text = _load_body_text_for_llm(
                    body_text_path=str(ar.body_text_path)
                    if ar.body_text_path
                    else None,
                    body_html_path=str(ar.body_html_path)
                    if ar.body_html_path
                    else None,
                )
                multimodal_inputs: list[LlmImageInput] | None = None
                if wants_multimodal_inputs(provider, s):
                    selected_inputs = select_multimodal_inputs(
                        base_dir=paths.base_dir,
                        attachments=list(ar.attachments or []),
                        external_assets=list(ar.external_assets or []),
                    )
                    if selected_inputs:
                        multimodal_inputs = selected_inputs

                originally_seen = any(
                    (f.lower() == b"\\seen") for f in (m.flags or tuple())
                )

                return {
                    "i_global": i_global,
                    "m": m,
                    "hdr": hdr,
                    "subject": subject,
                    "display_date": display_date,
                    "display_sub": display_sub,
                    "paths": paths,
                    "ar": ar,
                    "msg_fk": msg_fk,
                    "body_text": body_text,
                    "multimodal_inputs": multimodal_inputs,
                    "originally_seen": originally_seen,
                }

            def _call_llm_direct(*, ctx: dict) -> tuple[LlmResult, float]:
                """Direct summarize_email_long_aware call for concurrent path.

                Returns (result, summarize_seconds). On timeout/exception returns
                a fallback LlmResult identical to _run_llm_summary semantics.

                예외 타입별 한국어 메시지 분기: timeout·네트워크·HTTP·파싱·기타.
                _is_llm_fallback 의 '(LLM ' startswith 패턴은 그대로 매칭됨.
                """
                # Lazy import: requests/json 은 _call_llm_direct 가
                # provider 미사용 환경에서도 모듈 로드되도록 함수 내부에서 import.
                import json as _json

                try:
                    import requests.exceptions as _rex
                except Exception:  # pragma: no cover - requests 미설치 환경
                    _rex = None  # type: ignore[assignment]
                from concurrent.futures import TimeoutError as _FutTimeout

                t1 = time.monotonic()
                try:
                    res = summarize_email_long_aware(
                        provider,
                        subject=sanitize_text_for_llm(str(ctx["subject"])),
                        body=sanitize_text_for_llm(ctx["body_text"]),
                        on_progress=None,
                        user_profile={
                            "roles": s.user_roles,
                            "interests": s.user_interests,
                        },
                        multimodal_inputs=ctx["multimodal_inputs"],
                    )
                except Exception as ex:
                    # 예외 타입별 한국어 메시지 분기. _is_llm_fallback 은
                    # '(LLM ' startswith 로 매칭하므로 모두 통과.
                    fallback_summary = "(LLM 호출 실패)"
                    if _rex is not None and isinstance(ex, _rex.Timeout):
                        fallback_summary = "(LLM 응답 timeout)"
                    elif isinstance(ex, _FutTimeout):
                        fallback_summary = "(LLM 응답 timeout)"
                    elif _rex is not None and isinstance(
                        ex, _rex.ConnectionError
                    ):
                        fallback_summary = "(LLM 네트워크 오류)"
                    elif _rex is not None and isinstance(ex, _rex.HTTPError):
                        fallback_summary = "(LLM HTTP 오류)"
                    elif isinstance(ex, _json.JSONDecodeError):
                        fallback_summary = "(LLM 응답 파싱 실패)"
                    _add_job_event(
                        db_path=db_path,
                        job_id=job_id,
                        level="warn",
                        text=f"LLM exception ({type(ex).__name__}): {str(ex)[:160]}",
                    )
                    res = LlmResult(
                        summary=fallback_summary,
                        tags=[],
                        backlinks=[],
                        personal=False,
                    )
                return res, time.monotonic() - t1

            def _is_llm_fallback(llm_res: LlmResult) -> bool:
                """Detect LlmResult produced by timeout / exception fallback.

                Worker `_call_llm_direct` returns (LLM unavailable) on any
                Exception. Concurrent path returns (LLM timeout) on future
                timeout. Both share the pattern: summary starts with
                '(LLM ' and tags/backlinks/personal are all empty/False.
                """
                s = str(getattr(llm_res, "summary", "") or "")
                if not s.startswith("(LLM "):
                    return False
                if llm_res.tags or llm_res.backlinks:
                    return False
                return True

            def _record_llm_fallback(
                *, ctx: dict, llm_res: LlmResult, dt2_s: float
            ) -> None:
                """Persist fallback summary so user can see what failed, but
                do NOT mark exported / seen. Next sync retries via
                get_incomplete_uids (seen_marked_at IS NULL).
                """
                i_global = ctx["i_global"]
                msg_fk = ctx["msg_fk"]
                with open_db(db_path) as conn_fb:
                    set_analysis(
                        conn_fb,
                        message_fk=msg_fk,
                        summary=llm_res.summary,
                        tags=[],
                        topics=[],
                        personal=False,
                        summarize_ms=int(max(0.0, dt2_s) * 1000.0),
                    )
                    conn_fb.commit()
                _add_job_event(
                    db_path=db_path,
                    job_id=job_id,
                    level="warn",
                    text=(
                        f"LLM 실패 메일 ({i_global}/{msg_total}): 다음 sync 때 자동 재시도합니다"
                    ),
                )

            def _persist_and_export_one(
                *,
                ctx: dict,
                llm_res: LlmResult,
                dt2_s: float,
                suppress_stage_update: bool = False,
            ) -> Path | None:
                """Save analysis, export Obsidian note. Returns note_path or None.

                B 3.1 최소 침습 conn pool: set_analysis + set_exported 를
                conn2 1개로 묶어서 phase 3 conn 3회 → 2회 (export 실패 시 1회).
                C P1-2 깜빡임 완화: suppress_stage_update=True 면 메일별
                _set_stage_for("export") skip (chunk_size>1 분기에서만 True).
                """
                i_global = ctx["i_global"]
                m = ctx["m"]
                subject = ctx["subject"]
                display_date = ctx["display_date"]
                display_sub = ctx["display_sub"]
                msg_fk = ctx["msg_fk"]
                paths = ctx["paths"]
                hdr = ctx["hdr"]
                topics = llm_res.backlinks

                if dt2_s > 60:
                    _add_job_event(
                        db_path=db_path,
                        job_id=job_id,
                        level="warn",
                        text=f"요약이 느립니다 ({dt2_s:.1f}초)",
                    )

                if not suppress_stage_update:
                    _set_stage_for(
                        i_global=i_global,
                        display_date=display_date,
                        subject=subject,
                        stage="export",
                    )
                email_dt = (
                    m.internaldate.date() if m.internaldate else dt.date.today()
                )

                with open_db(db_path) as conn2:
                    # set_analysis 먼저: export 실패해도 사용자가 요약 결과를
                    # day list 에서 볼 수 있도록 함.
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
                            current=i_global,
                            total=max(msg_total, 1),
                            message=f"[{display_date}] Obsidian 내보내기 실패 (계속): {display_sub} ({i_global}/{msg_total})",
                        )
                        return None

                    # 같은 conn 으로 set_exported 까지 묶음 (conn 2개 → 1개).
                    set_exported(conn2, message_fk=msg_fk)
                    conn2.commit()
                return note_path

            def _mark_one(
                *, ctx: dict, suppress_stage_update: bool = False
            ) -> None:
                """IMAP \\Seen 플래그 마킹 + DB seen_marked_at 갱신.

                C P1-3 깜빡임 완화: suppress_stage_update=True 면 메일별
                _set_stage_for("mark") skip (chunk_size>1 분기에서만 True).
                """
                i_global = ctx["i_global"]
                m = ctx["m"]
                subject = ctx["subject"]
                display_date = ctx["display_date"]
                msg_fk = ctx["msg_fk"]
                originally_seen = ctx["originally_seen"]

                if not suppress_stage_update:
                    _set_stage_for(
                        i_global=i_global,
                        display_date=display_date,
                        subject=subject,
                        stage="mark",
                    )
                try:
                    _mark_seen_retry(m.uid)
                    if revert_seen and not originally_seen:
                        to_revert.append(int(m.uid))
                    with open_db(db_path) as connm:
                        set_seen_marked(connm, message_fk=msg_fk)
                        connm.commit()
                except Exception as e:
                    with open_db(db_path) as connm2:
                        repo.add_event(
                            connm2,
                            job_id=job_id,
                            level="warn",
                            text=f"읽음 처리 실패: {e}",
                        )

            try:
                global_counter = 0
                for chunk in _chunked(msg_iter, chunk_size):
                    if cancel.is_set():
                        break

                    # Phase 1: Archive + index sequentially (DB / FS safety).
                    chunk_ctxs: list[dict] = []
                    for m in chunk:
                        if cancel.is_set():
                            break
                        global_counter += 1
                        ctx = _archive_and_index_one(global_counter, m)
                        chunk_ctxs.append(ctx)

                    if not chunk_ctxs:
                        break

                    # Phase 2: LLM calls (concurrent for chunk_size > 1).
                    _add_job_event(
                        db_path=db_path,
                        job_id=job_id,
                        level="info",
                        text="요약 시작",
                    )

                    # Cloud pacing applied once per chunk (shared rate budget).
                    if provider.__class__.__name__ == "CloudProvider":
                        time.sleep(
                            cloud_base_delay_seconds(
                                s.cloud_provider,
                                s.openrouter_model,
                            )
                        )

                    llm_outputs: list[tuple[LlmResult, float]] = []

                    if chunk_size <= 1:
                        # Serial path: keep existing heartbeat-based _run_llm_summary.
                        for ctx in chunk_ctxs:
                            i_global = ctx["i_global"]
                            display_date = ctx["display_date"]
                            display_sub = ctx["display_sub"]
                            _set_stage_for(
                                i_global=i_global,
                                display_date=display_date,
                                subject=ctx["subject"],
                                stage="summarize",
                            )

                            def _sub_progress(fraction: float, _i=i_global, _dd=display_date, _ds=display_sub) -> None:
                                _update_job_progress(
                                    db_path=db_path,
                                    job_id=job_id,
                                    current=_i - 1 + fraction,
                                    total=max(msg_total, 1),
                                    message=f"[{_dd}] 요약 중: {_ds} ({_i}/{msg_total})",
                                )

                            t1 = time.monotonic()
                            llm_res = _run_llm_summary(
                                db_path=db_path,
                                job_id=job_id,
                                provider=provider,
                                subject=ctx["subject"],
                                body_text=ctx["body_text"],
                                user_profile={
                                    "roles": s.user_roles,
                                    "interests": s.user_interests,
                                },
                                update_sub_progress=_sub_progress,
                                item_index=i_global,
                                item_total=msg_total,
                                display_date=display_date,
                                display_sub=display_sub,
                                multimodal_inputs=ctx["multimodal_inputs"],
                            )
                            llm_outputs.append(
                                (llm_res, time.monotonic() - t1)
                            )
                    else:
                        # Concurrent path: ThreadPoolExecutor over the chunk.
                        first = chunk_ctxs[0]
                        last = chunk_ctxs[-1]
                        chunk_msg_base = (
                            f"[{first['display_date']}] 요약 중 동시 처리 "
                            f"({first['i_global']}~{last['i_global']}/{msg_total})"
                        )
                        _update_job_progress(
                            db_path=db_path,
                            job_id=job_id,
                            current=first["i_global"] - 0.99,
                            total=max(msg_total, 1),
                            message=chunk_msg_base,
                        )

                        llm_timeout_s = llm_timeout_seconds(provider)

                        def _worker(ctx: dict) -> tuple[LlmResult, float]:
                            return _call_llm_direct(ctx=ctx)

                        # Heartbeat: cloud LLM 호출이 길어도 사용자에게
                        # 진행 중임을 알려준다. 주기마다 elapsed + 완료 카운트
                        # 표시. ThreadPool 종료 시 자동 정지.
                        chunk_done_count = [0]

                        def _chunk_heartbeat_tick(elapsed_s: float) -> None:
                            done = int(chunk_done_count[0])
                            _update_job_progress(
                                db_path=db_path,
                                job_id=job_id,
                                current=(
                                    first["i_global"]
                                    - 0.99
                                    + 0.99 * (done / max(len(chunk_ctxs), 1))
                                ),
                                total=max(msg_total, 1),
                                message=(
                                    f"{chunk_msg_base} "
                                    f"({done}/{len(chunk_ctxs)} 완료, "
                                    f"경과 {format_elapsed(elapsed_s)})"
                                ),
                            )

                        chunk_hb = Heartbeat(
                            _chunk_heartbeat_tick, name="chunk-heartbeat"
                        ).start()

                        try:
                            with ThreadPoolExecutor(
                                max_workers=len(chunk_ctxs)
                            ) as pool:
                                futures = [
                                    pool.submit(_worker, ctx)
                                    for ctx in chunk_ctxs
                                ]
                                # Cancel pending futures early when user
                                # presses stop. Already-running HTTP calls
                                # cannot be aborted (Python limitation), but
                                # not-yet-started ones get cancelled here.
                                for idx, fut in enumerate(futures):
                                    ctx = chunk_ctxs[idx]
                                    if cancel.is_set():
                                        # Cancel remaining pending futures.
                                        for f2 in futures[idx:]:
                                            f2.cancel()
                                        # Fill outputs for the rest as
                                        # fallback so Phase 3 zip works.
                                        for _ in futures[idx:]:
                                            llm_outputs.append(
                                                (
                                                    LlmResult(
                                                        summary="(LLM cancelled)",
                                                        tags=[],
                                                        backlinks=[],
                                                        personal=False,
                                                    ),
                                                    0.0,
                                                )
                                            )
                                        break
                                    try:
                                        res_pair = fut.result(
                                            timeout=llm_timeout_s
                                        )
                                    except Exception as ex:
                                        _add_job_event(
                                            db_path=db_path,
                                            job_id=job_id,
                                            level="warn",
                                            text=(
                                                f"LLM 호출 timeout "
                                                f"({ctx['i_global']}/{msg_total}, "
                                                f"대기 {llm_timeout_s:.0f}초): "
                                                f"{str(ex)[:140]}"
                                            ),
                                        )
                                        res_pair = (
                                            LlmResult(
                                                summary="(LLM timeout)",
                                                tags=[],
                                                backlinks=[],
                                                personal=False,
                                            ),
                                            float(llm_timeout_s),
                                        )
                                    llm_outputs.append(res_pair)
                                    chunk_done_count[0] += 1
                        finally:
                            chunk_hb.stop()

                    # Phase 3: Persist, export, mark in chunk order.
                    # LLM fallback (timeout / unavailable) detection: skip
                    # export + mark so the message stays seen_marked_at=NULL
                    # and gets retried on the next sync via
                    # get_incomplete_uids. set_analysis is still called so
                    # the user can see "(LLM timeout)" in the day list and
                    # understand why retry is pending.
                    #
                    # C P1-2/1-3 깜빡임 완화: chunk_size>1 분기에서는
                    # 메일별 _set_stage_for 호출을 skip 하고 chunk 단위
                    # 1회만 progress 갱신. chunk_size=1 분기는 회귀 위험
                    # 0 을 위해 기존 동작 유지.
                    suppress_stage = chunk_size > 1
                    if suppress_stage and chunk_ctxs:
                        _first = chunk_ctxs[0]
                        _last = chunk_ctxs[-1]
                        _update_job_progress(
                            db_path=db_path,
                            job_id=job_id,
                            current=_first["i_global"],
                            total=max(msg_total, 1),
                            message=(
                                f"[{_first['display_date']}] 저장·읽음 처리 중 "
                                f"({_first['i_global']}~{_last['i_global']}/{msg_total})"
                            ),
                        )
                    for ctx, (llm_res, dt2_s) in zip(chunk_ctxs, llm_outputs):
                        if cancel.is_set():
                            break
                        if _is_llm_fallback(llm_res):
                            _record_llm_fallback(
                                ctx=ctx, llm_res=llm_res, dt2_s=dt2_s
                            )
                            continue
                        note_path = _persist_and_export_one(
                            ctx=ctx,
                            llm_res=llm_res,
                            dt2_s=dt2_s,
                            suppress_stage_update=suppress_stage,
                        )
                        if note_path is None:
                            continue
                        _mark_one(
                            ctx=ctx, suppress_stage_update=suppress_stage
                        )

                        m = ctx["m"]
                        date_prefix = (
                            m.internaldate.date().isoformat()
                            if m.internaldate
                            else dt.date.today().isoformat()
                        )
                        processed_notes.append(
                            (date_prefix, note_path, llm_res.backlinks)
                        )

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
                            with open_db(db_path) as connw:
                                repo.add_event(
                                    connw,
                                    job_id=job_id,
                                    level="warn",
                                    text=f"안읽음 원복 실패: {e}",
                                )

    return run
