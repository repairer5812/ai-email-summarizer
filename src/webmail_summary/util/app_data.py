from __future__ import annotations

import os
import platform
from pathlib import Path


def _platform_key() -> str:
    return (platform.system() or "").strip().lower()


def get_app_data_dir() -> Path:
    sys_name = _platform_key()
    if sys_name == "windows":
        base = os.environ.get("LOCALAPPDATA")
        p = Path(base) / "WebmailSummary" if base else Path.home() / ".webmail-summary"
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
