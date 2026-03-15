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


def _bring_to_front_path() -> Path:
    return _runtime_dir() / "ui_bring_to_front.txt"


def _ui_pid_path() -> Path:
    return _runtime_dir() / "ui_pid.txt"


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


def write_ui_pid(pid: int) -> None:
    _ui_pid_path().write_text(str(int(pid)), encoding="utf-8")


def clear_ui_pid() -> None:
    try:
        _ui_pid_path().unlink(missing_ok=True)
    except Exception:
        pass


def read_ui_pid() -> int:
    try:
        v = _ui_pid_path().read_text(encoding="utf-8", errors="replace").strip()
        return int(v)
    except Exception:
        return 0


def signal_bring_to_front(ts: float | None = None) -> None:
    _write_ts(_bring_to_front_path(), float(ts if ts is not None else time.time()))


def read_bring_to_front_ts() -> float:
    return _read_ts(_bring_to_front_path())


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
