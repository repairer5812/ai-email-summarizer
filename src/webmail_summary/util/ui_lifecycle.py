from __future__ import annotations

import time
from pathlib import Path

from webmail_summary.util.app_data import get_app_data_dir


def _runtime_dir() -> Path:
    p = get_app_data_dir() / "runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _heartbeat_path() -> Path:
    return _runtime_dir() / "ui_heartbeat.txt"


def _tab_closed_path() -> Path:
    return _runtime_dir() / "ui_tab_closed.txt"


def _write_ts(path: Path, ts: float) -> None:
    path.write_text(f"{ts:.6f}", encoding="utf-8")


def _read_ts(path: Path) -> float:
    try:
        return float(path.read_text(encoding="utf-8", errors="replace").strip() or "0")
    except Exception:
        return 0.0


def mark_ui_heartbeat(ts: float | None = None) -> None:
    _write_ts(_heartbeat_path(), float(ts if ts is not None else time.time()))


def mark_ui_tab_closed(ts: float | None = None) -> None:
    _write_ts(_tab_closed_path(), float(ts if ts is not None else time.time()))


def should_exit_for_ui_close(
    close_behavior: str,
    *,
    now: float | None = None,
    close_grace_seconds: float = 8.0,
) -> bool:
    mode = str(close_behavior or "background").strip().lower()
    if mode != "exit":
        return False

    ts_now = float(now if now is not None else time.time())
    ts_closed = _read_ts(_tab_closed_path())
    if ts_closed <= 0.0:
        return False

    ts_heartbeat = _read_ts(_heartbeat_path())
    # If heartbeat is newer than close mark, there is at least one active tab.
    if ts_heartbeat >= ts_closed:
        return False

    return (ts_now - ts_closed) >= float(close_grace_seconds)
