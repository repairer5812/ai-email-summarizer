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


def physical_core_count() -> int | None:
    """Number of physical CPU cores (P + E on Intel hybrid), or None."""
    try:
        import psutil

        n = psutil.cpu_count(logical=False)
        return int(n) if n else None
    except Exception:
        return None


def performance_core_count() -> int | None:
    """Best-effort count of high-performance CPU cores.

    On Intel hybrid CPUs (Alder Lake / Meteor Lake and later) only the
    P-cores expose Hyper-Threading, so ``logical - physical`` equals the
    P-core count (e.g. Core Ultra 5 125H: 18 logical - 14 physical = 4 P).
    On classic SMT CPUs this also yields the physical-core count.  Returns
    None when topology cannot be inferred (no HT, or detection failed).
    """
    import os

    logical = os.cpu_count() or 0
    physical = physical_core_count() or 0
    if logical and physical and logical > physical:
        return logical - physical
    return None


def optimal_cpu_threads(override: int = 0) -> int:
    """Recommended llama.cpp CPU thread count for this machine.

    *override* > 0 wins (explicit user setting).  Otherwise prefer the
    P-core count on hybrid CPUs and the physical-core count elsewhere.
    Rationale: llama.cpp is slowed when work spills onto E-cores because
    the fast P-cores finish first and then stall waiting on the slower
    E-cores, so overall throughput is capped at E-core speed
    (ggml-org/llama.cpp#572 measured 2.4-3x by pinning to P-cores).
    """
    import os

    try:
        if int(override) > 0:
            return max(1, int(override))
    except Exception:
        pass

    chosen = performance_core_count()
    if not chosen or chosen < 1:
        chosen = physical_core_count() or (os.cpu_count() or 4)
    return max(1, min(int(chosen), 16))


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
