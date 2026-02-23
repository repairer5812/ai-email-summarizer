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
