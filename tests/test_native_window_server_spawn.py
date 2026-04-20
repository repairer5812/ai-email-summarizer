from pathlib import Path

from webmail_summary.util.process_control import build_fresh_pyinstaller_env
from webmail_summary.ui import frozen_extensions, native_window


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
    native_attempts: list[str] = []

    monkeypatch.setattr(native_window, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(native_window, "SingleInstanceLock", lambda path: _DummyLock())
    monkeypatch.setattr(native_window, "write_ui_pid", lambda pid: None)
    monkeypatch.setattr(native_window, "clear_ui_pid", lambda: None)
    monkeypatch.setattr(native_window.time, "sleep", lambda *_args, **_kwargs: None)
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
        lambda *args, **kwargs: native_attempts.append("try")
        or (_ for _ in ()).throw(RuntimeError("coreclr missing")),
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

    assert native_attempts == ["try", "try"]
    assert len(opened) == 1
    assert "http://127.0.0.1:9999/" in opened[0]
    assert "ui_notice=native_fallback" in opened[0]
    assert "ui_reason=RuntimeError%3A+coreclr+missing" in opened[0]
    assert shown_errors == []
    log_text = (tmp_path / "logs" / "ui_start.log").read_text(encoding="utf-8")
    assert "native_window attempt=1 next_action=retry" in log_text
    assert "native_window attempt=2 next_action=browser_fallback" in log_text


def test_open_browser_fallback_prefers_windows_app_mode(monkeypatch):
    launched: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(native_window, "is_windows", lambda: True)
    monkeypatch.setattr(
        native_window,
        "_windows_app_mode_browsers",
        lambda: [Path("C:/Program Files/Google/Chrome/Application/chrome.exe")],
    )
    monkeypatch.setattr(
        native_window.subprocess,
        "Popen",
        lambda args, **kwargs: launched.append((list(args), kwargs)) or object(),
    )
    monkeypatch.setattr(native_window.webbrowser, "open", lambda url: False)

    mode = native_window._open_browser_fallback("http://127.0.0.1:9999/")

    assert mode == "app"
    assert launched
    assert launched[0][0][0].endswith("chrome.exe")
    assert launched[0][0][1].startswith("--app=http://127.0.0.1:9999/")
    assert "ui_window=app" in launched[0][0][1]


def test_run_ui_retries_native_window_once_before_browser_fallback(
    monkeypatch, tmp_path
):
    opened: list[str] = []
    shown_errors: list[tuple[str, str]] = []
    native_attempts: list[str] = []

    monkeypatch.setattr(native_window, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(native_window, "SingleInstanceLock", lambda path: _DummyLock())
    monkeypatch.setattr(native_window, "write_ui_pid", lambda pid: None)
    monkeypatch.setattr(native_window, "clear_ui_pid", lambda: None)
    monkeypatch.setattr(native_window.time, "sleep", lambda *_args, **_kwargs: None)
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

    def _run_once_then_succeed(*args, **kwargs):
        native_attempts.append("try")
        if len(native_attempts) == 1:
            raise RuntimeError("temporary webview init failure")
        return None

    monkeypatch.setattr(native_window, "_run_native_window", _run_once_then_succeed)
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

    assert native_attempts == ["try", "try"]
    assert opened == []
    assert shown_errors == []
    log_text = (tmp_path / "logs" / "ui_start.log").read_text(encoding="utf-8")
    assert "native_window attempt=1 next_action=retry" in log_text
    assert "browser_fallback" not in log_text


def test_short_error_reason_prefers_nested_import_failure():
    root = ModuleNotFoundError("No module named '_cffi_backend'")
    outer = RuntimeError("Failed to create a .NET runtime (coreclr) using the parameters {}.")
    outer.__cause__ = root

    text = native_window._short_error_reason(outer)

    assert text == "ModuleNotFoundError: No module named '_cffi_backend'"


def test_ensure_frozen_extension_alias_creates_plain_pyd_copy(monkeypatch, tmp_path):
    mei = tmp_path / "_MEI123"
    mei.mkdir()
    tagged = mei / "_cffi_backend.cp311-win_amd64.pyd"
    tagged.write_bytes(b"stub")

    monkeypatch.setattr(frozen_extensions.sys, "frozen", True, raising=False)
    monkeypatch.setattr(frozen_extensions.sys, "_MEIPASS", str(mei), raising=False)

    aliased = native_window._ensure_frozen_extension_alias("_cffi_backend")

    assert aliased == mei / "_cffi_backend.pyd"
    assert aliased.read_bytes() == b"stub"


def test_preload_frozen_cffi_backend_retries_after_creating_alias(
    monkeypatch, tmp_path
):
    mei = tmp_path / "_MEI123"
    mei.mkdir()
    (mei / "_cffi_backend.cp311-win_amd64.pyd").write_bytes(b"stub")

    monkeypatch.setattr(frozen_extensions.sys, "frozen", True, raising=False)
    monkeypatch.setattr(frozen_extensions.sys, "_MEIPASS", str(mei), raising=False)

    imported = {"count": 0}

    def _fake_import(name):
        assert name == "_cffi_backend"
        imported["count"] += 1
        if imported["count"] == 1:
            raise ModuleNotFoundError("No module named '_cffi_backend'")
        return object()

    monkeypatch.setattr(frozen_extensions.importlib, "import_module", _fake_import)

    native_window._preload_frozen_cffi_backend()

    assert imported["count"] == 2
    assert (mei / "_cffi_backend.pyd").is_file()
