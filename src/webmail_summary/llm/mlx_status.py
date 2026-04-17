"""Status checks for MLX engine and model readiness."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from webmail_summary.llm.local_models import get_local_model
from webmail_summary.llm.mlx_engine import find_mlx_installed
from webmail_summary.util.platform_caps import is_apple_silicon

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MlxReady:
    apple_silicon: bool
    mlx_installed: bool
    model_cached: bool
    model_path: str | None


def _hf_cache_dir() -> Path:
    """Return the default HuggingFace cache directory."""
    import os

    env = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "huggingface" / "hub"


def _is_model_cached(hf_repo_id: str) -> tuple[bool, str | None]:
    """Check if an MLX model repo is already in the HF cache."""
    cache = _hf_cache_dir()
    # HuggingFace cache uses models--<org>--<name> directory naming.
    safe_name = "models--" + hf_repo_id.replace("/", "--")
    model_dir = cache / safe_name
    if not model_dir.exists():
        return False, None
    # Check for a snapshots dir with at least one snapshot.
    snapshots = model_dir / "snapshots"
    if snapshots.exists() and any(snapshots.iterdir()):
        return True, str(snapshots)
    return False, None


def check_mlx_ready(*, model_id: str) -> MlxReady:
    """Check readiness of MLX engine for the given model."""
    apple_silicon = is_apple_silicon()
    mlx_inst = find_mlx_installed()
    mlx_installed = mlx_inst is not None

    m = get_local_model(model_id)
    if m.engine != "mlx":
        return MlxReady(
            apple_silicon=apple_silicon,
            mlx_installed=mlx_installed,
            model_cached=False,
            model_path=None,
        )

    cached, path = _is_model_cached(m.hf_repo_id)
    return MlxReady(
        apple_silicon=apple_silicon,
        mlx_installed=mlx_installed,
        model_cached=cached,
        model_path=path,
    )
