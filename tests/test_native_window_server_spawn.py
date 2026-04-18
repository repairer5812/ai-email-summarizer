from webmail_summary.util.process_control import build_fresh_pyinstaller_env


def test_fresh_pyinstaller_env_resets_to_new_top_level_process(monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "0")

    env = build_fresh_pyinstaller_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_ARCHIVE_FILE" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env
