from __future__ import annotations

from datetime import timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:
    # Windows Python can be missing system tzdata. Fall back to a fixed offset.
    KST = timezone(timedelta(hours=9))
