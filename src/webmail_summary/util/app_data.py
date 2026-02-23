from __future__ import annotations

import os
from pathlib import Path


def get_app_data_dir() -> Path:
    # Use LOCALAPPDATA for larger local caches.
    base = os.environ.get("LOCALAPPDATA")
    if base:
        p = Path(base) / "WebmailSummary"
    else:
        p = Path.home() / ".webmail-summary"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_obsidian_root() -> Path:
    # Windows desktop default; fallback to home.
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop / "Tekville_Obsidian"
    return Path.home() / "Tekville_Obsidian"


def get_models_dir() -> Path:
    p = get_app_data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_engines_dir() -> Path:
    p = get_app_data_dir() / "engines"
    p.mkdir(parents=True, exist_ok=True)
    return p
