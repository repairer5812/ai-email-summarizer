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


def test_install_on_logon_task_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(caps, "system_name", lambda: "darwin")

    try:
        install_on_logon_task(task_name="x", command="y")
    except RuntimeError as e:
        assert "only supported on Windows" in str(e)
    else:
        raise AssertionError("expected RuntimeError on non-Windows")
