from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from webmail_summary.api.routes_jobs import router as api_router
from webmail_summary.api.routes_openrouter import router as openrouter_router
from webmail_summary.index.db import get_conn, init_db
from webmail_summary.llm.local_status import delete_gguf_and_marker
from webmail_summary.ui.routes import router as ui_router
from webmail_summary.util.app_data import get_app_data_dir


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

    # DNS rebinding / cross-origin CSRF guard. Server binds to 127.0.0.1 only,
    # but any browser tab (including a malicious external site via a DNS
    # rebinding attack) could otherwise reach the loopback API. Restrict
    # Host header to loopback literals.
    _ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

    @app.middleware("http")
    async def _enforce_loopback_host(request: Request, call_next):
        host_header = (request.headers.get("host") or "").strip()
        host_only = host_header.split(":", 1)[0].lower() if host_header else ""
        if host_only and host_only not in _ALLOWED_HOSTS:
            return PlainTextResponse("forbidden host", status_code=403)
        # Reject cross-origin requests outright (Origin set, not loopback).
        origin = (request.headers.get("origin") or "").strip().lower()
        if origin:
            try:
                from urllib.parse import urlparse as _u
                o_host = (_u(origin).hostname or "").lower()
            except Exception:
                o_host = ""
            if o_host and o_host not in {"127.0.0.1", "localhost", "::1"}:
                return PlainTextResponse("forbidden origin", status_code=403)
        return await call_next(request)

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


