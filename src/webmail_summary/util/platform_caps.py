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
