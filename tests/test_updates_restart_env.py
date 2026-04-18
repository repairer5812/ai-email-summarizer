from pathlib import Path

from webmail_summary.ui.updates import _write_updater_script
from webmail_summary.util.process_control import build_fresh_pyinstaller_env


def test_build_fresh_pyinstaller_env_clears_private_vars(monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_SPLASH_IPC", "12345")
    monkeypatch.setenv("_MEIPASS2", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("NORMAL_VAR", "keep-me")

    env = build_fresh_pyinstaller_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["NORMAL_VAR"] == "keep-me"
    assert "_PYI_ARCHIVE_FILE" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "_PYI_PARENT_PROCESS_LEVEL" not in env
    assert "_PYI_SPLASH_IPC" not in env
    assert "_MEIPASS2" not in env


def test_write_updater_script_resets_pyinstaller_env_before_relaunch(tmp_path: Path):
    script_path = tmp_path / "apply_update.ps1"
    _write_updater_script(script_path)
    text = script_path.read_text(encoding="utf-8-sig")

    assert "function Reset-PyInstallerEnv()" in text
    assert "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'" in text
    assert "$vv.Name -like '_PYI_*' -or $vv.Name -eq '_MEIPASS2'" in text
    assert "Reset-PyInstallerEnv" in text
