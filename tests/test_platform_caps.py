from __future__ import annotations

import webmail_summary.util.platform_caps as caps
import webmail_summary.util.process_control as proc
from webmail_summary.startup_task import install_on_logon_task


def test_ui_platform_caps_non_windows(monkeypatch):
    monkeypatch.setattr(caps, "system_name", lambda: "darwin")

    info = caps.ui_platform_caps()

    assert info.use_native_window is False
    assert info.startup_task_supported is False


def test_hidden_subprocess_kwargs_empty_on_non_windows(monkeypatch):
    monkeypatch.setattr(proc, "is_windows", lambda: False)
    assert proc.hidden_subprocess_kwargs() == {}
    assert proc.detached_subprocess_kwargs() == {}


def test_is_apple_silicon_on_darwin_arm64(monkeypatch):
    monkeypatch.setattr(caps, "is_macos", lambda: True)
    monkeypatch.setattr(caps.platform, "machine", lambda: "arm64")
    assert caps.is_apple_silicon() is True


def test_is_apple_silicon_on_darwin_x86(monkeypatch):
    monkeypatch.setattr(caps, "is_macos", lambda: True)
    monkeypatch.setattr(caps.platform, "machine", lambda: "x86_64")
    assert caps.is_apple_silicon() is False


def test_is_apple_silicon_on_windows(monkeypatch):
    monkeypatch.setattr(caps, "is_macos", lambda: False)
    monkeypatch.setattr(caps.platform, "machine", lambda: "arm64")
    assert caps.is_apple_silicon() is False


def test_is_mlx_available_not_apple_silicon(monkeypatch):
    monkeypatch.setattr(caps, "is_apple_silicon", lambda: False)
    assert caps.is_mlx_available() is False


def test_install_on_logon_task_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(caps, "system_name", lambda: "darwin")

    try:
        install_on_logon_task(task_name="x", command="y")
    except RuntimeError as e:
        assert "only supported on Windows" in str(e)
    else:
        raise AssertionError("expected RuntimeError on non-Windows")
