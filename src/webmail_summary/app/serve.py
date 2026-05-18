from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from webmail_summary.app.main import create_app
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.single_instance import SingleInstanceLock
from webmail_summary.util.ui_lifecycle import should_exit_for_ui_close


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _load_close_behavior(data_dir: Path) -> str:
    from webmail_summary.index.db import get_conn

    conn = get_conn(data_dir / "db.sqlite3")
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("close_behavior",)
        ).fetchone()
    finally:
        conn.close()
    v = str(row[0] if row else "background").strip().lower()
    if v not in {"background", "exit"}:
        return "background"
    return v


def _force_exit_process() -> None:
    import _thread

    from webmail_summary.jobs.runner import get_runner
    from webmail_summary.llm.llamacpp_server import stop_server

    try:
        get_runner().terminate_all()
    except Exception:
        pass
    try:
        stop_server(force=True)
    except Exception:
        pass
    try:
        _thread.interrupt_main()
    except Exception:
        pass

    deadline = time.time() + 8.0
    while time.time() < deadline:
        time.sleep(0.1)
    os._exit(0)


@dataclass(frozen=True)
class ServeOptions:
    host: str = "127.0.0.1"
    port: int | None = None
    open_browser: bool = True


def serve(opts: ServeOptions = ServeOptions()) -> None:
    data_dir = get_app_data_dir()
    lock = SingleInstanceLock(data_dir / "serve.lock")
    url_path = data_dir / "active_url.txt"

    if not lock.acquire():
        if opts.open_browser:
            try:
                existing = url_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            except Exception:
                existing = ""
            existing_url = existing.splitlines()[0].strip() if existing else ""
            if existing_url.startswith("http://") or existing_url.startswith("https://"):
                webbrowser.open(existing_url)
        return

    app = create_app()
    port = opts.port or _find_free_port()
    url = f"http://{opts.host}:{port}/"
    stop_watchdog = threading.Event()

    def _close_watchdog() -> None:
        while not stop_watchdog.wait(2.0):
            try:
                mode = _load_close_behavior(data_dir)
                if should_exit_for_ui_close(mode):
                    _force_exit_process()
                    return
            except Exception:
                continue

    watchdog = threading.Thread(target=_close_watchdog, daemon=True)
    watchdog.start()

    @app.on_event("startup")
    def _publish_active_url() -> None:
        handshake = os.environ.get("WEBMAIL_SUMMARY_HANDSHAKE", "")
        try:
            url_path.write_text(
                f"{url}\n{os.getpid()}\n{handshake}\n", encoding="utf-8"
            )
        except Exception:
            pass
        if opts.open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        def _run_update_check() -> None:
            try:
                from webmail_summary.index.db import get_conn
                from webmail_summary.index.settings import load_settings
                from webmail_summary.ui.updates import _check_github_release

                conn = get_conn(data_dir / "db.sqlite3")
                try:
                    settings = load_settings(conn)
                    if not settings.update_auto_check_enabled:
                        return
                    _check_github_release(conn, settings, force=True)
                finally:
                    conn.close()
            except Exception:
                pass

        threading.Thread(
            target=_run_update_check, daemon=True, name="update-startup-check"
        ).start()

    try:
        if getattr(sys, "frozen", False):
            log_dir = data_dir / "logs"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / "server.log"
                stream = open(log_path, "a", encoding="utf-8", buffering=1)
            except Exception:
                stream = open(os.devnull, "w", encoding="utf-8")

            if getattr(sys, "stdout", None) is None:
                sys.stdout = stream
            if getattr(sys, "stderr", None) is None:
                sys.stderr = stream

        uvicorn.run(app, host=opts.host, port=port, log_level="info", use_colors=False)
    finally:
        stop_watchdog.set()
        try:
            url_path.unlink(missing_ok=True)
        except Exception:
            pass
        lock.release()
