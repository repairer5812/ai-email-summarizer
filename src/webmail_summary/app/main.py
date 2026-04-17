from __future__ import annotations

import socket
import webbrowser
from dataclasses import dataclass
from pathlib import Path
import sys
import os
import time
import _thread
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from webmail_summary.index.db import init_db
from webmail_summary.index.db import get_conn
from webmail_summary.api.routes_jobs import router as api_router
from webmail_summary.api.routes_openrouter import router as openrouter_router
from webmail_summary.ui.routes import router as ui_router
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.single_instance import SingleInstanceLock
from webmail_summary.llm.local_status import delete_gguf_and_marker
from webmail_summary.util.ui_lifecycle import should_exit_for_ui_close


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _load_close_behavior(data_dir: Path) -> str:
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

    # Graceful shutdown first; hard-exit only as a bounded fallback.
    deadline = time.time() + 8.0
    while time.time() < deadline:
        time.sleep(0.1)
    os._exit(0)


def _cleanup_stale_mei_dirs() -> None:
    """Remove leftover _MEI* temp dirs from previous PyInstaller runs.

    These directories can hold stale python3xx.dll files that cause
    "Failed to load Python DLL" errors on the next launch after an update.
    Only cleans dirs that are NOT owned by the currently running process.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import tempfile

        temp = Path(tempfile.gettempdir())
        current_mei = getattr(sys, "_MEIPASS", "")
        for d in temp.iterdir():
            if not d.is_dir() or not d.name.startswith("_MEI"):
                continue
            if current_mei and str(d) == current_mei:
                continue  # don't delete our own
            try:
                import shutil

                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="Webmail Summary", docs_url=None, redoc_url=None)

    @app.get("/favicon.ico")
    def favicon():
        return RedirectResponse(url="/static/app-icon.png", status_code=307)

    _cleanup_stale_mei_dirs()

    data_dir = get_app_data_dir()
    init_db(data_dir / "db.sqlite3")

    # Remove legacy ultra model artifacts (Qwen2.5 0.5B) if present.
    delete_gguf_and_marker(
        hf_repo_id="bartowski/Qwen2.5-0.5B-Instruct-GGUF",
        hf_filename="Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    )
    # Also remove the failed Qwen 1.5B model.
    delete_gguf_and_marker(
        hf_repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        hf_filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    )

    # On restart, background jobs are not resumed. Mark any previously active
    # jobs as failed so the UI doesn't get stuck watching old job IDs.
    conn = get_conn(data_dir / "db.sqlite3")
    try:
        conn.execute(
            "UPDATE jobs SET status='failed', message='recovered on startup', updated_at=datetime('now') "
            "WHERE status IN ('queued','running')"
        )
        conn.execute(
            "UPDATE jobs SET status='cancelled', message='recovered as cancelled', updated_at=datetime('now') "
            "WHERE status IN ('cancel_requested')"
        )
        conn.commit()
    finally:
        conn.close()

    # Static assets (CSS)
    static_dir = Path(__file__).resolve().parents[1] / "ui" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(api_router)
    app.include_router(openrouter_router)
    app.include_router(ui_router)

    @app.on_event("shutdown")
    def shutdown_event():
        from webmail_summary.jobs.runner import get_runner
        from webmail_summary.llm.llamacpp_server import stop_server

        get_runner().terminate_all()
        stop_server(force=True)

    return app


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
            if existing.startswith("http://") or existing.startswith("https://"):
                webbrowser.open(existing)
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

    try:
        try:
            url_path.write_text(url, encoding="utf-8")
        except Exception:
            pass
        if opts.open_browser:
            webbrowser.open(url)

        # In PyInstaller --noconsole builds, stdio can be None. Uvicorn's default
        # log formatters may call isatty() on sys.stderr; ensure it's always safe.
        if getattr(sys, "frozen", False):
            data_dir = get_app_data_dir()
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
