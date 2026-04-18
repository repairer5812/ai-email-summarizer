from __future__ import annotations

import os
import signal
import subprocess

from webmail_summary.util.platform_caps import is_windows


def build_fresh_pyinstaller_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict that forces a fresh PyInstaller process instance.

    This is needed when a frozen onefile executable launches another copy of
    itself that should not reuse the current process' private ``_PYI_*`` /
    ``_MEIPASS2`` state. Reusing that state can bind the new process to a temp
    extraction directory owned by the parent instance, which becomes fragile
    across app restarts and updates.
    """
    env = dict(base_env or os.environ)
    for key in list(env.keys()):
        if key.startswith("_PYI_") or key == "_MEIPASS2":
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


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
