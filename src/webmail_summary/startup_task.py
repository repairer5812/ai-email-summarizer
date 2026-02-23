from __future__ import annotations

import subprocess
from pathlib import Path


def install_on_logon_task(*, task_name: str, command: str) -> None:
    # Requires admin depending on target settings.
    # This is intentionally explicit (not automatic) for safety.
    subprocess.run(
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
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", task_name], check=False)
