from __future__ import annotations

import os
import platform
from pathlib import Path


def _platform_key() -> str:
    return (platform.system() or "").strip().lower()


def _expand_env_dir(value: str | None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    expanded = os.path.expanduser(os.path.expandvars(raw)).strip()
    if not expanded:
        return None
    return Path(expanded)


def get_app_data_dir() -> Path:
    sys_name = _platform_key()
    if sys_name == "windows":
        base = _expand_env_dir(os.environ.get("LOCALAPPDATA"))
        p = base / "WebmailSummary" if base else Path.home() / ".webmail-summary"
    elif sys_name == "darwin":
        p = Path.home() / "Library" / "Application Support" / "WebmailSummary"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        p = (
            Path(xdg) / "WebmailSummary"
            if xdg
            else Path.home() / ".local" / "share" / "WebmailSummary"
        )
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_obsidian_root() -> Path:
    sys_name = _platform_key()
    if sys_name == "darwin":
        docs = Path.home() / "Documents"
        if docs.exists():
            return docs / "Tekville_Obsidian"
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop / "Tekville_Obsidian"
    docs = Path.home() / "Documents"
    if docs.exists():
        return docs / "Tekville_Obsidian"
    return Path.home() / "Tekville_Obsidian"


def get_models_dir() -> Path:
    p = get_app_data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_engines_dir() -> Path:
    p = get_app_data_dir() / "engines"
    p.mkdir(parents=True, exist_ok=True)
    return p
