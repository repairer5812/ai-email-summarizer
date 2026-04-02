from __future__ import annotations

import os
import signal
import subprocess

from webmail_summary.util.platform_caps import is_windows


def hidden_subprocess_kwargs() -> dict:
    if not is_windows():
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": si,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def detached_subprocess_kwargs() -> dict:
    if not is_windows():
        return {}
    return {
        "creationflags": (
            int(getattr(subprocess, "DETACHED_PROCESS", 0))
            | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        )
    }


def run_quiet_command(cmd: list[str], *, check: bool = False) -> None:
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "check": check,
    }
    kwargs.update(hidden_subprocess_kwargs())
    subprocess.run(cmd, **kwargs)


def terminate_process_tree(pid: int) -> None:
    if is_windows():
        run_quiet_command(["taskkill", "/PID", str(int(pid)), "/T", "/F"], check=False)
        return
    os.kill(int(pid), signal.SIGTERM)
