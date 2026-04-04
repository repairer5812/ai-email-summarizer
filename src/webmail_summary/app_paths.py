from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path

    @property
    def config_path(self) -> Path:
        return self.base_dir / "config.json"

    @property
    def state_path(self) -> Path:
        return self.base_dir / "state.json"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"


def _expand_env_dir(value: str | None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    expanded = os.path.expanduser(os.path.expandvars(raw)).strip()
    if not expanded:
        return None
    return Path(expanded)


def get_app_paths() -> AppPaths:
    appdata = _expand_env_dir(os.environ.get("APPDATA"))
    if appdata:
        base = appdata / "WebmailSummary"
    else:
        base = Path.home() / ".webmail-summary"
    base.mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)
    return AppPaths(base_dir=base)
