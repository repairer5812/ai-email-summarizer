from __future__ import annotations

from pathlib import Path

import webmail_summary.app_paths as mod


def test_get_app_paths_expands_literal_windows_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TEMP", str(tmp_path / "temp-root"))
    monkeypatch.setenv("APPDATA", "%TEMP%")

    paths = mod.get_app_paths()

    assert paths.base_dir == tmp_path / "temp-root" / "WebmailSummary"
    assert paths.logs_dir == tmp_path / "temp-root" / "WebmailSummary" / "logs"
