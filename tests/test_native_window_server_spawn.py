from webmail_summary.util.process_control import build_fresh_pyinstaller_env
from webmail_summary.ui import native_window


def test_fresh_pyinstaller_env_resets_to_new_top_level_process(monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "0")

    env = build_fresh_pyinstaller_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_ARCHIVE_FILE" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env


class _DummyLock:
    def acquire(self):
        return True

    def release(self):
        return None


class _DummyProc:
    def poll(self):
        return None


def test_run_ui_falls_back_to_browser_when_native_window_fails(monkeypatch, tmp_path):
    opened: list[str] = []
    shown_errors: list[tuple[str, str]] = []

    monkeypatch.setattr(native_window, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(native_window, "SingleInstanceLock", lambda path: _DummyLock())
    monkeypatch.setattr(native_window, "write_ui_pid", lambda pid: None)
    monkeypatch.setattr(native_window, "clear_ui_pid", lambda: None)
    monkeypatch.setattr(native_window, "_is_reachable", lambda url: False)
    monkeypatch.setattr(native_window, "_server_command", lambda port: ["fake-app"])
    monkeypatch.setattr(
        native_window.subprocess,
        "Popen",
        lambda *args, **kwargs: _DummyProc(),
    )
    monkeypatch.setattr(
        native_window,
        "_wait_for_active_url_change",
        lambda *args, **kwargs: "http://127.0.0.1:9999/",
    )
    monkeypatch.setattr(
        native_window,
        "_wait_for_http_ready",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        native_window,
        "_run_native_window",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("coreclr missing")),
    )
    monkeypatch.setattr(
        native_window,
        "_open_browser_fallback",
        lambda url: opened.append(url) or True,
    )
    monkeypatch.setattr(
        native_window,
        "_show_error",
        lambda title, message: shown_errors.append((title, message)),
    )

    native_window.run_ui(port=0)

    assert opened == ["http://127.0.0.1:9999/"]
    assert shown_errors == []
