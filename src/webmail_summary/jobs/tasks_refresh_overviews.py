from __future__ import annotations

import re
import threading
from datetime import datetime
from collections.abc import Callable
from pathlib import Path
from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import set_daily_overview
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs import repo
from webmail_summary.llm.provider import get_llm_provider
from webmail_summary.llm.long_summarize import synthesize_daily_overview
from webmail_summary.util.app_data import get_app_data_dir


def refresh_overviews_task(
    date_keys: list[str] | None = None,
    force_refresh: bool = False,
) -> Callable[[str, threading.Event], None]:
    def _normalize_days(raw_days: list[str] | None) -> list[str]:
        if not raw_days:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for d in raw_days:
            day = str(d or "").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            if day in seen:
                continue
            seen.add(day)
            out.append(day)
        return out

    def run(job_id: str, cancel: threading.Event) -> None:
        db_path = get_app_data_dir() / "db.sqlite3"
        conn = get_conn(db_path)
        try:
            s = load_settings(conn)
            provider = get_llm_provider(s)

            normalized_days = _normalize_days(date_keys)

            if normalized_days:
                days = normalized_days
            else:
                # Find all unique days
                rows = conn.execute(
                    "SELECT DISTINCT substr(internal_date, 1, 10) as day "
                    "FROM messages WHERE internal_date IS NOT NULL "
                    "ORDER BY day DESC LIMIT 90"
                ).fetchall()
                days = [str(r[0]) for r in rows if r[0]]

            total = len(days)
            if total <= 0:
                repo.update_progress(
                    conn,
                    job_id=job_id,
                    current=0,
                    total=0,
                    message="대상 날짜가 없습니다",
                )
                return

            for i, d in enumerate(days, start=1):
                if cancel.is_set():
                    break

                repo.update_progress(
                    conn,
                    job_id=job_id,
                    current=i - 0.5,
                    total=total,
                    message=f"[{d}] 날짜별요약 생성 중 ({i}/{total})",
                )

                refreshed = refresh_overviews_for_dates(
                    db_path=db_path,
                    provider=provider,
                    settings=s,
                    date_keys=[d],
                    force_refresh=(force_refresh or bool(normalized_days)),
                    job_id=job_id,
                )
                if not refreshed:
                    repo.update_progress(
                        conn,
                        job_id=job_id,
                        current=float(i),
                        total=total,
                        message=f"[{d}] 최신 상태 (건너뜀)",
                    )
                    continue

                repo.update_progress(
                    conn,
                    job_id=job_id,
                    current=float(i),
                    total=total,
                    message=f"[{d}] 날짜별요약 생성 완료",
                )

        finally:
            conn.close()

    return run


def refresh_overviews_for_dates(
    *,
    db_path: Path,
    provider,
    settings,
    date_keys: list[str],
    force_refresh: bool = True,
    job_id: str | None = None,
) -> list[str]:
    def _normalize_days(raw_days: list[str] | None) -> list[str]:
        if not raw_days:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for d in raw_days:
            day = str(d or "").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            if day in seen:
                continue
            seen.add(day)
            out.append(day)
        return out

    def _parse_iso(ts: str | None) -> datetime | None:
        if not ts:
            return None
        s = str(ts).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    normalized_days = _normalize_days(date_keys)
    if not normalized_days:
        return []

    refreshed: list[str] = []
    conn = get_conn(db_path)
    try:
        for d in normalized_days:
            day_conn = get_conn(db_path)
            try:
                ts_row = day_conn.execute(
                    "SELECT "
                    "(SELECT MAX(summarized_at) FROM messages WHERE internal_date LIKE ? AND summarized_at IS NOT NULL), "
                    "(SELECT updated_at FROM daily_overviews WHERE day = ?)",
                    (f"{d}%", d),
                ).fetchone()
                max_msg_ts = _parse_iso(ts_row[0] if ts_row else None)
                ov_ts = _parse_iso(ts_row[1] if ts_row else None)
                if (
                    not force_refresh
                    and max_msg_ts is not None
                    and ov_ts is not None
                    and ov_ts >= max_msg_ts
                ):
                    if job_id:
                        repo.add_event(
                            conn,
                            job_id=job_id,
                            level="info",
                            text=f"[{d}] 최신 상태라 건너뜀",
                        )
                    continue

                rows = day_conn.execute(
                    "SELECT summary FROM messages "
                    "WHERE internal_date LIKE ? AND summary IS NOT NULL AND trim(summary) <> '' "
                    "ORDER BY internal_date ASC",
                    (f"{d}%",),
                ).fetchall()
                # Exclude failed/placeholder summaries from the overview
                # input — otherwise the daily digest inherits those strings.
                from webmail_summary.jobs.tasks_resummarize import _needs_resummarize

                all_sums = [
                    str(r[0] or "")
                    for r in rows
                    if r[0] and not _needs_resummarize(str(r[0] or ""))
                ]

                if not all_sums:
                    if job_id:
                        repo.add_event(
                            conn,
                            job_id=job_id,
                            level="info",
                            text=f"[{d}] 요약 데이터가 없어 건너뜀",
                        )
                    continue

                user_profile = {
                    "roles": settings.user_roles,
                    "interests": settings.user_interests,
                }
                overview = synthesize_daily_overview(
                    provider,
                    day=d,
                    summaries=all_sums,
                    user_profile=user_profile,
                )
                if overview:
                    set_daily_overview(day_conn, day=d, overview=overview)
                    day_conn.commit()
                    refreshed.append(d)
                elif job_id:
                    repo.add_event(
                        conn,
                        job_id=job_id,
                        level="warn",
                        text=f"[{d}] 날짜별요약 생성 결과가 비어 있어 건너뜀",
                    )
            except Exception as e:
                if job_id:
                    repo.add_event(
                        conn,
                        job_id=job_id,
                        level="error",
                        text=f"[{d}] 개요 생성 실패: {e}",
                    )
            finally:
                day_conn.close()
    finally:
        conn.close()

    return refreshed
