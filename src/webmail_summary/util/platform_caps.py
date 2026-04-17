from __future__ import annotations

import platform
from dataclasses import dataclass


def system_name() -> str:
    return (platform.system() or "").strip().lower()


def is_windows() -> bool:
    return system_name() == "windows"


def is_macos() -> bool:
    return system_name() == "darwin"


def is_linux() -> bool:
    return system_name() == "linux"


def is_apple_silicon() -> bool:
    """Return True on macOS with arm64 (M1/M2/M3/M4)."""
    return is_macos() and (platform.machine() or "").strip().lower() == "arm64"


def is_mlx_available() -> bool:
    """Return True if the ``mlx`` package can be imported (macOS Apple Silicon only)."""
    if not is_apple_silicon():
        return False
    try:
        import importlib  # noqa: E401

        importlib.import_module("mlx")
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class UiPlatformCaps:
    use_native_window: bool
    startup_task_supported: bool


def ui_platform_caps() -> UiPlatformCaps:
    windows = is_windows()
    return UiPlatformCaps(
        use_native_window=windows,
        startup_task_supported=windows,
    )
