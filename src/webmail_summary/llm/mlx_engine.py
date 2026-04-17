"""MLX runtime detection and installation helpers.

mlx-lm is NOT added to requirements.txt (macOS-only).
Instead, we install it at runtime via pip or detect an existing installation.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from webmail_summary.util.platform_caps import is_apple_silicon

log = logging.getLogger(__name__)

# Minimum mlx-lm version required for /v1/chat/completions endpoint.
_MIN_MLX_LM_VERSION = "0.22.0"


@dataclass(frozen=True)
class MlxInstall:
    python: str  # path to python that has mlx-lm
    server_cmd: list[str]  # command to launch mlx_lm.server


class MlxNotSupported(RuntimeError):
    """Raised when the platform does not support MLX."""


class MlxInstallError(RuntimeError):
    """Raised when mlx-lm installation fails."""


def _find_mlx_lm_python() -> str | None:
    """Return the python executable that has mlx_lm installed, or None."""
    for py in [sys.executable, shutil.which("python3") or "", shutil.which("python") or ""]:
        if not py:
            continue
        try:
            result = subprocess.run(
                [py, "-c", "import mlx_lm; print(mlx_lm.__version__)"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                log.info("Found mlx-lm %s at %s", version, py)
                return py
        except Exception:
            continue
    return None


def find_mlx_installed() -> MlxInstall | None:
    """Return MlxInstall if mlx-lm is installed, or None."""
    if not is_apple_silicon():
        return None
    py = _find_mlx_lm_python()
    if not py:
        return None
    return MlxInstall(
        python=py,
        server_cmd=[py, "-m", "mlx_lm.server"],
    )


def ensure_mlx_installed() -> MlxInstall:
    """Install mlx-lm if needed and return MlxInstall.

    Raises MlxNotSupported on non-Apple-Silicon platforms.
    Raises MlxInstallError on installation failure.
    """
    if not is_apple_silicon():
        raise MlxNotSupported("MLX requires macOS with Apple Silicon (M1+)")

    existing = find_mlx_installed()
    if existing:
        return existing

    log.info("Installing mlx-lm via pip...")
    py = sys.executable
    try:
        subprocess.run(
            [py, "-m", "pip", "install", "--quiet", f"mlx-lm>={_MIN_MLX_LM_VERSION}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as e:
        raise MlxInstallError(f"pip install mlx-lm failed: {e.stderr[:500]}") from e
    except subprocess.TimeoutExpired:
        raise MlxInstallError("pip install mlx-lm timed out (5 min)")

    installed = find_mlx_installed()
    if not installed:
        raise MlxInstallError("mlx-lm installed but cannot be imported")
    return installed
