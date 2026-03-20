from __future__ import annotations

import subprocess


def _run_quiet(cmd: list[str], *, check: bool) -> None:
    kwargs: dict = {"check": check}
    if subprocess.DEVNULL is not None:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run(cmd, **kwargs)


def install_on_logon_task(*, task_name: str, command: str) -> None:
    # Requires admin depending on target settings.
    # This is intentionally explicit (not automatic) for safety.
    _run_quiet(
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
    _run_quiet(["schtasks", "/Delete", "/F", "/TN", task_name], check=False)
