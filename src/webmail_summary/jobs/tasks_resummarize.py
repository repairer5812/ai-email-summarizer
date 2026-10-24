from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from webmail_summary.export.obsidian.exporter import (
    MessageExportInput,
    email_note_filename,
    export_daily_note,
    export_email_note,
    export_topic_note,
)
from webmail_summary.export.obsidian.naming import safe_topic_name
from webmail_summary.index.db import app_db_path, open_db
from webmail_summary.index.mail_repo import (
    get_message_ids_by_topic,
    list_messages_for_resummarize_by_date,
    list_messages_for_resummarize_by_dates,
    list_messages_for_resummarize_by_ids,
    set_analysis,
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
    load_stored_multimodal_inputs,
    wants_multimodal_inputs,
)
from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_for_dates
from webmail_summary.llm.base import LlmImageInput, LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider
from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.text_sanitize import (
    html_to_visible_text,
    prepare_body_for_llm,
    sanitize_text_for_llm,
)


log = logging.getLogger(__name__)


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
    if "llm error" in s or "(llm error" in s:
        return True
    if "failed to format input" in s or "invalid codepoint" in s:
        return True
    if "loading model" in s or "available commands" in s:
        return True
    if s.startswith("{") or s.startswith("```json") or s.startswith("```"):
        return True
    return False


class _ResummarizeCancelled(Exception):
    """Raised from the LLM callbacks once the user stops the job."""


@dataclass
class _ResummarizeRun:
    """State shared by the steps of one resummarize run."""

    job_id: str
    cancel: threading.Event
    data_dir: Path
    db_path: Path
    day_keys: list[str]
    only_failed: bool
    settings: Any = None
    provider: Any = None
    vault_root: Path | None = None
    targets: list = field(default_factory=list)
    processed_notes_by_day: dict[str, list[Path]] = field(default_factory=dict)
    touched_day_keys: set[str] = field(default_factory=set)
    all_topics: dict[str, list[Path]] = field(default_factory=dict)
    processed_count: int = 0

    @property
    def single_day_key(self) -> str:
        return self.day_keys[0] if len(self.day_keys) == 1 else ""

    @property
    def single_day(self) -> dt.date | None:
        key = self.single_day_key
        return _parse_date_key(key) if key else None

    @property
    def is_multi_day(self) -> bool:
        return len(self.day_keys) > 1

    @property
    def total(self) -> int:
        return max(len(self.targets), 1)

    def scope_message(self, *, single: str, multi: str) -> str:
        return single if not self.is_multi_day else multi

    def item_message(
        self,
        display_date: str,
        display_sub: str,
        index: int,
        total: int,
        *,
        llm: bool = False,
        elapsed: str = "",
    ) -> str:
        if self.is_multi_day:
            stage = "선택 날짜 LLM 호출 중" if llm else "선택 날짜 다시 요약 중"
            base = f"{stage} {display_date} / {display_sub} ({index}/{total})"
        else:
            stage = "LLM 호출 중" if llm else "다시 요약 중"
            base = f"[{display_date}] {stage} {display_sub} ({index}/{total})"
        if elapsed:
            return f"{base} {elapsed}"
        return base

    def prepare_message(self) -> str:
        return self.scope_message(
            single=f"[{self.single_day_key}] 날짜별 다시 요약 준비 중",
            multi=(
                f"선택 날짜 {len(self.day_keys)}일 "
                + ("오류만 다시 요약 준비 중" if self.only_failed else "전체 다시 요약 준비 중")
            ),
        )

    def empty_message(self) -> str:
        return self.scope_message(
            single=f"[{self.single_day_key}] 다시 요약 대상 없음",
            multi=(
                "선택 날짜에 오류 요약 대상이 없습니다"
                if self.only_failed
                else "선택 날짜에 다시 요약할 대상이 없습니다"
            ),
        )

    def cancelled_message(self) -> str:
        return self.scope_message(
            single=f"[{self.single_day_key}] 다시 요약 취소됨",
            multi="선택 날짜 다시 요약 취소됨",
        )

    def completed_message(self) -> str:
        return self.scope_message(
            single=f"[{self.single_day_key}] 다시 요약 완료",
            multi="선택 날짜 다시 요약 완료",
        )

    def add_event(self, level: str, text: str) -> None:
        with open_db(self.db_path) as conn:
            repo.add_event(conn, job_id=self.job_id, level=level, text=text)

    def add_detail(self, payload: dict) -> None:
        self.add_event("detail", json.dumps(payload, ensure_ascii=True))


@dataclass
class _ResummarizeItem:
    """One stored message as read back for resummarizing."""

    index: int
    msg_id: int
    account_id: str
    uidvalidity: int
    uid: int
    subject: str
    from_addr: str
    internal_date: str
    raw_eml_path: str
    body_text_path: str
    body_html_path: str
    old_topics: list[str]
    display_date: str
    display_sub: str
    archive_dir: Path


def _start_resummarize_run(
    job_id: str,
    cancel: threading.Event,
    *,
    date_key: str,
    date_keys: list[str] | None,
    only_failed: bool,
    message_ids: list[int] | None,
) -> _ResummarizeRun:
    """Validate the scope, then load settings and the LLM provider."""
    data_dir = get_app_data_dir()
    db_path = app_db_path(data_dir)

    day_keys = _normalize_date_keys(date_key=date_key, date_keys=date_keys)
    if not day_keys:
        raise RuntimeError("date_key required")
    if message_ids and len(day_keys) != 1:
        raise RuntimeError("message_ids require exactly one date")

    run = _ResummarizeRun(
        job_id=job_id,
        cancel=cancel,
        data_dir=data_dir,
        db_path=db_path,
        day_keys=day_keys,
        only_failed=only_failed,
    )
    # Fail early on a bad single date key, as before.
    _ = run.single_day

    with open_db(db_path) as conn:
        run.settings = load_settings(conn)

    try:
        run.provider = get_llm_provider(run.settings)
    except LlmNotReady as e:
        with open_db(db_path) as connr:
            repo.add_event(connr, job_id=job_id, level="error", text=str(e))
            repo.set_job_status(
                connr, job_id=job_id, status="failed", message=str(e)
            )
        raise

    run.add_event("info", f"llm_provider={run.provider.__class__.__name__}")

    settings = run.settings
    run.vault_root = (
        Path(settings.obsidian_root)
        if settings.obsidian_root
        else default_obsidian_root()
    )
    run.vault_root.mkdir(parents=True, exist_ok=True)
    return run


def _load_targets(run: _ResummarizeRun, *, message_ids: list[int] | None) -> None:
    """Pick the stored messages to resummarize and report the plan."""
    with open_db(run.db_path) as conn0:
        if message_ids:
            rows = list_messages_for_resummarize_by_ids(
                conn0, message_ids=list(message_ids)
            )
        elif len(run.day_keys) == 1:
            rows = list_messages_for_resummarize_by_date(
                conn0, date_prefix=run.day_keys[0]
            )
        else:
            rows = list_messages_for_resummarize_by_dates(
                conn0, date_keys=list(run.day_keys)
            )

    if message_ids:
        run.targets = rows
    elif run.only_failed:
        run.targets = [r for r in rows if _needs_resummarize(str(r[8] or ""))]
    else:
        run.targets = rows

    with open_db(run.db_path) as connp:
        repo.update_progress(
            connp,
            job_id=run.job_id,
            current=0,
            total=run.total,
            message=run.prepare_message(),
        )
        repo.add_event(
            connp,
            job_id=run.job_id,
            level="info",
            text=f"resummarize days={','.join(run.day_keys)} targets={len(run.targets)}",
        )


def _read_item(run: _ResummarizeRun, i: int, r) -> _ResummarizeItem:
    subject = str(r[5] or "(no subject)")
    internal_date = str(r[7] or "")
    raw_eml_path = str(r[9] or "")

    old_topics: list[str] = []
    try:
        old_topics = json.loads(str(r[12] or "[]")) or []
    except Exception:
        old_topics = []

    return _ResummarizeItem(
        index=i,
        msg_id=int(r[0]),
        account_id=str(r[1] or ""),
        uidvalidity=int(r[3] or 0),
        uid=int(r[4] or 0),
        subject=subject,
        from_addr=str(r[6] or run.settings.sender_filter or ""),
        internal_date=internal_date,
        raw_eml_path=raw_eml_path,
        body_text_path=str(r[10] or ""),
        body_html_path=str(r[11] or ""),
        old_topics=old_topics,
        display_date=internal_date[:10]
        if len(internal_date) >= 10
        else run.single_day_key,
        display_sub=(subject[:30] + "...") if len(subject) > 30 else subject,
        archive_dir=Path(raw_eml_path).parent if raw_eml_path else run.data_dir,
    )


def _read_archived_body(run: _ResummarizeRun, item: _ResummarizeItem) -> str:
    """Report the item start and read its archived body (text, else HTML)."""
    targets_n = len(run.targets)
    with open_db(run.db_path) as connx:
        repo.update_progress(
            connx,
            job_id=run.job_id,
            current=item.index - 0.99,
            total=run.total,
            message=run.item_message(
                item.display_date, item.display_sub, item.index, targets_n
            ),
        )
        repo.add_event(
            connx,
            job_id=run.job_id,
            level="info",
            text=f"item {item.index}/{targets_n}: {item.subject}",
        )
        repo.add_event(
            connx,
            job_id=run.job_id,
            level="detail",
            text=json.dumps(
                {
                    "type": "email",
                    "message_id": item.msg_id,
                    "index": item.index,
                    "total": targets_n,
                    "subject": item.subject,
                },
                ensure_ascii=True,
            ),
        )
        repo.add_event(
            connx,
            job_id=run.job_id,
            level="detail",
            text=json.dumps({"type": "stage", "stage": "read"}, ensure_ascii=True),
        )

    body_text = ""
    p_txt = Path(item.body_text_path) if item.body_text_path else None
    p_html = Path(item.body_html_path) if item.body_html_path else None
    if p_txt and p_txt.exists():
        body_text = p_txt.read_text(encoding="utf-8", errors="replace")
    elif p_html and p_html.exists():
        raw_html = p_html.read_text(encoding="utf-8", errors="replace")
        body_text = html_to_visible_text(raw_html)

    return prepare_body_for_llm(body_text)


def _summarize_item(
    run: _ResummarizeRun, item: _ResummarizeItem, body_text: str
) -> tuple[LlmResult, float] | None:
    """Run the LLM for one item.

    Returns (result, seconds since the call started, cloud pacing included),
    or None when the job was cancelled.
    """
    i = item.index
    targets_n = len(run.targets)
    cancel = run.cancel
    settings = run.settings
    provider = run.provider

    multimodal_inputs: list[LlmImageInput] | None = None
    if wants_multimodal_inputs(provider, settings):
        with open_db(run.db_path) as conn_mm:
            selected_inputs = load_stored_multimodal_inputs(
                conn_mm, message_fk=item.msg_id, base_dir=item.archive_dir
            )
        if selected_inputs:
            multimodal_inputs = selected_inputs

    with open_db(run.db_path) as connw:
        repo.update_progress(
            connw,
            job_id=run.job_id,
            current=i - 0.95,
            total=run.total,
            message=run.item_message(
                item.display_date, item.display_sub, i, targets_n, llm=True
            ),
        )
        repo.add_event(
            connw,
            job_id=run.job_id,
            level="detail",
            text=json.dumps({"type": "stage", "stage": "llm"}, ensure_ascii=True),
        )

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
        run.add_detail(d)

    def update_sub_progress(fraction: float) -> None:
        if cancel.is_set():
            raise _ResummarizeCancelled()
        _set_fraction(fraction)
        with open_db(run.db_path) as conn_p:
            repo.update_progress(
                conn_p,
                job_id=run.job_id,
                current=i - 1 + fraction,
                total=run.total,
                message=run.item_message(
                    item.display_date, item.display_sub, i, targets_n
                ),
            )

    t0 = time.monotonic()
    if provider.__class__.__name__ == "CloudProvider":
        time.sleep(
            cloud_base_delay_seconds(
                settings.cloud_provider,
                settings.openrouter_model,
            )
        )

    user_profile = {
        "roles": settings.user_roles,
        "interests": settings.user_interests,
    }

    def _heartbeat_tick(elapsed_s: float) -> None:
        with frac_lock:
            frac = float(last_fraction)
        cur = max(i - 0.95, (i - 1) + frac)
        with open_db(run.db_path) as conn_hb:
            repo.update_progress(
                conn_hb,
                job_id=run.job_id,
                current=cur,
                total=run.total,
                message=run.item_message(
                    item.display_date,
                    item.display_sub,
                    i,
                    targets_n,
                    llm=True,
                    elapsed=f"(경과 {format_elapsed(elapsed_s)})",
                ),
            )

    llm_timeout_s = llm_timeout_seconds(provider)

    def _log_timeout() -> None:
        run.add_event(
            "warn", f"LLM timeout: {llm_timeout_s:.0f}s (item {i}/{targets_n})"
        )

    outcome = call_with_deadline(
        lambda: summarize_email_long_aware(
            provider,
            subject=sanitize_text_for_llm(item.subject),
            body=sanitize_text_for_llm(body_text),
            on_detail=emit_detail,
            on_progress=update_sub_progress,
            user_profile=user_profile,
            multimodal_inputs=multimodal_inputs,
        ),
        timeout_s=llm_timeout_s,
        heartbeat=Heartbeat(_heartbeat_tick, cancel=cancel),
        on_timeout=_log_timeout,
    )
    llm_err = outcome.error
    if outcome.timed_out:
        llm_res = fallback_result("(LLM timeout)")
    else:
        llm_res = outcome.result
        if llm_res is None:
            if llm_err is not None:
                if isinstance(llm_err, _ResummarizeCancelled):
                    cancel.set()
                    return None
                run.add_event("warn", f"LLM exception: {str(llm_err)[:180]}")
            llm_res = fallback_result("(LLM unavailable)")

    if cancel.is_set() or isinstance(llm_err, _ResummarizeCancelled):
        cancel.set()
        return None
    return llm_res, time.monotonic() - t0


def _save_item(
    run: _ResummarizeRun, item: _ResummarizeItem, llm_res: LlmResult, dt_s: float
) -> None:
    """Store the new summary and tell the open day view about it."""
    i = item.index
    targets_n = len(run.targets)
    run.add_detail({"type": "stage", "stage": "save"})

    if dt_s > 60:
        run.add_event("warn", f"LLM 경고: {dt_s:.1f}s (item {i}/{targets_n})")
    else:
        run.add_event("info", f"LLM 완료: {dt_s:.1f}s (item {i}/{targets_n})")

    with open_db(run.db_path) as connu:
        set_analysis(
            connu,
            message_fk=item.msg_id,
            summary=llm_res.summary,
            tags=llm_res.tags,
            topics=llm_res.backlinks,
            personal=llm_res.personal,
            summarize_ms=int(max(0.0, dt_s) * 1000.0),
        )
        connu.commit()

    if item.display_date:
        run.touched_day_keys.add(item.display_date)
    run.processed_count = i

    run.add_event(
        "message_updated",
        json.dumps(
            {"message_id": item.msg_id, "summary": llm_res.summary},
            ensure_ascii=True,
        ),
    )


def _export_item(run: _ResummarizeRun, item: _ResummarizeItem, llm_res: LlmResult) -> None:
    """Rewrite the email note; remember its day and old/new topics."""
    run.add_detail({"type": "stage", "stage": "export"})
    topics = llm_res.backlinks
    try:
        try:
            email_dt = dt.datetime.fromisoformat(item.internal_date).date()
        except Exception:
            email_dt = run.single_day or _parse_date_key(run.day_keys[0])

        note_path = export_email_note(
            vault_root=run.vault_root,
            inp=MessageExportInput(
                message_key=f"{item.account_id}-{item.uidvalidity}-{item.uid}",
                date=email_dt,
                sender=item.from_addr,
                subject=item.subject,
                summary=llm_res.summary,
                tags=llm_res.tags,
                topics=topics,
                archive_dir=item.archive_dir,
            ),
        )
        run.processed_notes_by_day.setdefault(item.display_date, []).append(note_path)
        for t in topics:
            run.all_topics.setdefault(t, []).append(note_path)
        for t in item.old_topics:
            if t not in run.all_topics:
                run.all_topics[t] = []
    except Exception:
        log.debug("email note export failed for message %s", item.msg_id, exc_info=True)


def _resummarize_item(run: _ResummarizeRun, i: int, r) -> bool:
    """Read, summarize, save and export one message. False once cancelled."""
    item = _read_item(run, i, r)
    body_text = _read_archived_body(run, item)
    summarized = _summarize_item(run, item, body_text)
    if summarized is None:
        return False
    llm_res, dt_s = summarized
    _save_item(run, item, llm_res, dt_s)
    _export_item(run, item, llm_res)
    return True


def _refresh_topic_notes(run: _ResummarizeRun) -> None:
    """Rebuild every touched topic note from the DB; drop empty topics."""
    vault_root = run.vault_root
    for topic in run.all_topics:
        try:
            with open_db(run.db_path) as conn_topic:
                remaining = get_message_ids_by_topic(conn_topic, topic=topic)

            if not remaining:
                topic_file = vault_root / "Topic" / f"{safe_topic_name(topic)}.md"
                if topic_file.exists():
                    topic_file.unlink(missing_ok=True)
                continue

            topic_notes: list[Path] = []
            with open_db(run.db_path) as conn_notes:
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

            export_topic_note(
                vault_root=vault_root,
                topic=topic,
                message_notes=topic_notes,
                replace=True,
            )
        except Exception:
            log.debug("topic note refresh failed for %r", topic, exc_info=True)


def _finish_exports(run: _ResummarizeRun) -> None:
    """Daily notes, daily overviews and topic notes for the touched days."""
    try:
        for day_key, processed_notes in run.processed_notes_by_day.items():
            if not processed_notes:
                continue
            daily_summary = "\n".join(f"- {p.stem}" for p in processed_notes)
            export_daily_note(
                vault_root=run.vault_root,
                date=_parse_date_key(day_key),
                message_notes=processed_notes,
                daily_summary=daily_summary,
            )

        if run.touched_day_keys:
            refresh_overviews_for_dates(
                db_path=run.db_path,
                provider=run.provider,
                settings=run.settings,
                date_keys=sorted(run.touched_day_keys),
                force_refresh=True,
                job_id=run.job_id,
            )

        _refresh_topic_notes(run)
    except Exception:
        log.debug("resummarize post-processing failed", exc_info=True)


def resummarize_day_task(
    *,
    date_key: str = "",
    date_keys: list[str] | None = None,
    only_failed: bool = True,
    message_ids: list[int] | None = None,
):
    def run(job_id: str, cancel: threading.Event) -> None:
        state = _start_resummarize_run(
            job_id,
            cancel,
            date_key=date_key,
            date_keys=date_keys,
            only_failed=only_failed,
            message_ids=message_ids,
        )
        _load_targets(state, message_ids=message_ids)

        if not state.targets:
            with open_db(state.db_path) as connz:
                repo.update_progress(
                    connz,
                    job_id=job_id,
                    current=1,
                    total=1,
                    message=state.empty_message(),
                )
                repo.add_event(connz, job_id=job_id, level="info", text="no targets")
            return

        for i, r in enumerate(state.targets, start=1):
            if cancel.is_set():
                break
            if not _resummarize_item(state, i, r):
                break

        if cancel.is_set():
            with open_db(state.db_path) as connc:
                repo.update_progress(
                    connc,
                    job_id=job_id,
                    current=float(state.processed_count),
                    total=state.total,
                    message=state.cancelled_message(),
                )
                repo.add_event(connc, job_id=job_id, level="info", text="cancelled")
            return

        _finish_exports(state)

        with open_db(state.db_path) as connf:
            repo.update_progress(
                connf,
                job_id=job_id,
                current=len(state.targets),
                total=state.total,
                message=state.completed_message(),
            )

    return run
