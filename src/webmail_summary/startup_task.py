from __future__ import annotations

from webmail_summary.util.process_control import run_quiet_command
from webmail_summary.util.platform_caps import ui_platform_caps


def install_on_logon_task(*, task_name: str, command: str) -> None:
    if not ui_platform_caps().startup_task_supported:
        raise RuntimeError("startup task is only supported on Windows")
    # Requires admin depending on target settings.
    # This is intentionally explicit (not automatic) for safety.
    run_quiet_command(
        [
            "schtasks",
            "/Create",
            "/F",
            "/SC",
            "ONLOGON",
            "/TN",
            task_name,
            "/TR",
            command,
        ],
        check=True,
    )


def uninstall_task(*, task_name: str) -> None:
    if not ui_platform_caps().startup_task_supported:
        return
    run_quiet_command(["schtasks", "/Delete", "/F", "/TN", task_name], check=False)
