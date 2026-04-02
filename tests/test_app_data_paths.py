from __future__ import annotations

from pathlib import Path

import webmail_summary.util.app_data as mod


def test_get_app_data_dir_uses_macos_application_support(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod, "_platform_key", lambda: "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    p = mod.get_app_data_dir()

    assert p == tmp_path / "Library" / "Application Support" / "WebmailSummary"


def test_get_app_data_dir_uses_xdg_on_linux(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod, "_platform_key", lambda: "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    p = mod.get_app_data_dir()

    assert p == tmp_path / "xdg" / "WebmailSummary"


def test_default_obsidian_root_prefers_documents_on_macos(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod, "_platform_key", lambda: "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents").mkdir()

    p = mod.default_obsidian_root()

    assert p == tmp_path / "Documents" / "Tekville_Obsidian"
