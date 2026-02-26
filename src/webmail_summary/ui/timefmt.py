from __future__ import annotations

from datetime import datetime
from datetime import timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:
    # Windows Python can be missing system tzdata. Fall back to a fixed offset.
    KST = timezone(timedelta(hours=9))


def _parse_iso(s: str) -> datetime | None:
    ss = (s or "").strip()
    if not ss:
        return None
    try:
        dt = datetime.fromisoformat(ss)
    except Exception:
        return None
    if dt.tzinfo is None:
        # Treat naive timestamps as KST for display.
        return dt.replace(tzinfo=KST)
    return dt


def to_kst(iso: str) -> datetime | None:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    return dt.astimezone(KST)


def date_key_kst(iso: str) -> str:
    dt = to_kst(iso)
    if dt is None:
        s = (iso or "").strip()
        return s[:10] if len(s) >= 10 else "unknown"
    return dt.date().isoformat()


def format_kst(iso: str, *, with_seconds: bool = True) -> str:
    dt = to_kst(iso)
    if dt is None:
        return (iso or "").strip() or ""
    if with_seconds:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M")


def time_kst(iso: str, *, with_seconds: bool = True) -> str:
    dt = to_kst(iso)
    if dt is None:
        return ""
    return dt.strftime("%H:%M:%S" if with_seconds else "%H:%M")


def format_date_with_weekday_ko(iso_date: str) -> str:
    """Format YYYY-MM-DD to YYYY-MM-DD(요일)."""
    s = (iso_date or "").strip()
    if not s:
        return ""
    # Just take first 10 chars if it's a full timestamp.
    dstr = s[:10]
    try:
        dt = datetime.fromisoformat(dstr)
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        return f"{dstr}({weekdays[dt.weekday()]})"
    except Exception:
        return s
