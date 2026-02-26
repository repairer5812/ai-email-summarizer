from __future__ import annotations

import socket
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webmail_summary.index.db import init_db
from webmail_summary.index.db import get_conn
from webmail_summary.api.routes_jobs import router as api_router
from webmail_summary.ui.routes import router as ui_router
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.llm.local_status import delete_gguf_and_marker


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def create_app() -> FastAPI:
    app = FastAPI(title="Webmail Summary", docs_url=None, redoc_url=None)

    @app.get("/favicon.ico")
    def favicon():
        # Real favicon bytes (simple 16x16 BGRA square) so browsers show an icon.
        import struct

        from fastapi import Response

        w = 16
        h = 16

        # ICONDIR (6) + ICONDIRENTRY (16)
        header = struct.pack("<HHH", 0, 1, 1)

        # BITMAPINFOHEADER (40)
        biSize = 40
        biWidth = w
        biHeight = h * 2  # includes AND mask
        biPlanes = 1
        biBitCount = 32
        biCompression = 0
        biSizeImage = w * h * 4
        dib = struct.pack(
            "<IIIHHIIIIII",
            biSize,
            biWidth,
            biHeight,
            biPlanes,
            biBitCount,
            biCompression,
            biSizeImage,
            0,
            0,
            0,
            0,
        )

        # Pixel data (bottom-up). Solid teal-ish color.
        # BGRA = (0xD4,0xBF,0x2D,0xFF) ~ #2DBFD4
        px = bytes([0xD4, 0xBF, 0x2D, 0xFF])
        row = px * w
        pixels = row * h

        # AND mask: 1 bit per pixel, padded to 32-bit. All zeros = opaque.
        and_row_bytes = ((w + 31) // 32) * 4
        and_mask = b"\x00" * (and_row_bytes * h)

        image = dib + pixels + and_mask
        image_offset = 6 + 16
        entry = struct.pack(
            "<BBBBHHII",
            w,
            h,
            0,
            0,
            1,
            32,
            len(image),
            image_offset,
        )

        ico = header + entry + image
        return Response(content=ico, media_type="image/x-icon")

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
    app.include_router(ui_router)

    @app.on_event("shutdown")
    def shutdown_event():
        from webmail_summary.jobs.runner import get_runner
        get_runner().terminate_all()

    return app

    return app


@dataclass(frozen=True)
class ServeOptions:
    host: str = "127.0.0.1"
    port: int | None = None
    open_browser: bool = True


def serve(opts: ServeOptions = ServeOptions()) -> None:
    app = create_app()
    port = opts.port or _find_free_port()
    url = f"http://{opts.host}:{port}/"
    if opts.open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=opts.host, port=port, log_level="info")
