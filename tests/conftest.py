from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_data_dir(tmp_path, monkeypatch):
    """Point the app data dir at tmp_path on every OS.

    get_app_data_dir() reads LOCALAPPDATA on Windows and XDG_DATA_HOME on
    Linux. Tests that only set LOCALAPPDATA used to open the real Linux app
    database. Setting both keeps every test inside tmp_path/WebmailSummary.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
