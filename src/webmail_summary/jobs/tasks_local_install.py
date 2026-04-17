from __future__ import annotations

import threading
import time
from pathlib import Path

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.llm.hf_download import (
    DownloadCancelled,
    download_with_resume,
    hf_resolve_url,
)
from webmail_summary.llm.local_engine import (
    EngineInstallError,
    ensure_llama_cpp_installed,
)
from webmail_summary.llm.local_models import LOCAL_MODELS, get_local_model
from webmail_summary.llm.local_status import get_local_model_path
from webmail_summary.llm.local_status import get_local_model_complete_marker
from webmail_summary.llm.local_status import check_local_ready
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.app_data import get_models_dir
from webmail_summary.util.atomic_io import atomic_write_text


def _run_mlx_install(job_id: str, cancel: threading.Event, model_id_norm: str) -> None:
    """Install MLX engine + trigger model cache via a test server start."""
    from webmail_summary.llm.mlx_engine import ensure_mlx_installed, MlxNotSupported, MlxInstallError
    from webmail_summary.llm.mlx_status import check_mlx_ready

    db_path = get_app_data_dir() / "db.sqlite3"

    # Check if already cached.
    mlx_ready = check_mlx_ready(model_id=model_id_norm)
    if mlx_ready.mlx_installed and mlx_ready.model_cached:
        conn0 = get_conn(db_path)
        try:
            repo.update_progress(conn0, job_id=job_id, current=100, total=100, message="installed (MLX)")
            repo.add_event(conn0, job_id=job_id, level="info", text="MLX model already cached")
        finally:
            conn0.close()
        return

    # 1) Ensure mlx-lm is installed.
    conn = get_conn(db_path)
    try:
        repo.update_progress(conn, job_id=job_id, current=0, total=100, message="install mlx-lm")
    finally:
        conn.close()

    try:
        mlx_inst = ensure_mlx_installed()
    except (MlxNotSupported, MlxInstallError) as e:
        conn2 = get_conn(db_path)
        try:
            repo.add_event(conn2, job_id=job_id, level="error", text=str(e))
        finally:
            conn2.close()
        raise

    if cancel.is_set():
        return

    # 2) Trigger model download via mlx_lm.server dry-run.
    #    mlx_lm.server auto-downloads the model on first request to /v1/models.
    m = get_local_model(model_id_norm)
    conn3 = get_conn(db_path)
    try:
        repo.update_progress(conn3, job_id=job_id, current=30, total=100, message=f"download MLX model: {m.hf_repo_id}")
    finally:
        conn3.close()

    import subprocess, os
    cmd = [*mlx_inst.server_cmd, "--model", m.hf_repo_id, "--host", "127.0.0.1", "--port", "4899"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)

    # Wait for server to become ready (downloads model on first start).
    import requests as req
    deadline = time.monotonic() + 600  # 10 min for large model download
    ready = False
    while time.monotonic() < deadline:
        if cancel.is_set():
            proc.terminate()
            return
        if proc.poll() is not None:
            break
        try:
            r = req.get("http://127.0.0.1:4899/v1/models", timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(3)

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    conn4 = get_conn(db_path)
    try:
        if ready:
            repo.update_progress(conn4, job_id=job_id, current=100, total=100, message="installed (MLX)")
            repo.add_event(conn4, job_id=job_id, level="info", text=f"MLX model cached: {m.hf_repo_id}")
        else:
            repo.add_event(conn4, job_id=job_id, level="error", text="MLX model download/load failed")
            repo.update_progress(conn4, job_id=job_id, current=0, total=100, message="MLX install failed")
    finally:
        conn4.close()


def local_install_task(*, model_id: str):
    def run(job_id: str, cancel: threading.Event) -> None:
        db_path = get_app_data_dir() / "db.sqlite3"

        # Normalize model id.
        model_id_norm = get_local_model(model_id).id

        # MLX model → separate install path.
        m = get_local_model(model_id_norm)
        if m.engine == "mlx":
            _run_mlx_install(job_id, cancel, model_id_norm)
            return

        # Fast path: already installed (GGUF).
        try:
            ready = check_local_ready(model_id=model_id_norm)
            if bool(ready.engine_ok) and bool(ready.model_ok):
                conn0 = get_conn(db_path)
                try:
                    repo.update_progress(
                        conn0,
                        job_id=job_id,
                        current=100,
                        total=100,
                        message="installed",
                    )
                    repo.add_event(
                        conn0,
                        job_id=job_id,
                        level="info",
                        text="already installed",
                    )
                finally:
                    conn0.close()
                return
        except Exception:
            pass

        # 1) Ensure engine
        conn = get_conn(db_path)
        try:
            repo.update_progress(
                conn, job_id=job_id, current=0, total=100, message="install engine"
            )
        finally:
            conn.close()

        def _engine_progress(downloaded: int, total: int, msg: str) -> None:
            try:
                pct = int((downloaded / max(1, total)) * 30)  # engine = 0~30%
                conn_ep = get_conn(db_path)
                try:
                    repo.update_progress(
                        conn_ep,
                        job_id=job_id,
                        current=pct,
                        total=100,
                        message=msg,
                    )
                finally:
                    conn_ep.close()
            except Exception:
                pass

        try:
            inst = ensure_llama_cpp_installed(on_progress=_engine_progress)
        except EngineInstallError as e:
            conn2 = get_conn(db_path)
            try:
                repo.add_event(conn2, job_id=job_id, level="error", text=str(e))
            finally:
                conn2.close()
            raise

        # 2) Download model
        m = get_local_model(model_id_norm)
        out_path = get_local_model_path(model_id=model_id_norm)
        url = hf_resolve_url(m.hf_repo_id, m.hf_filename)

        def on_prog(p):
            if cancel.is_set():
                return

            # Throttle DB writes to avoid slowing downloads.
            nonlocal last_pct, last_emit_ts
            now = time.monotonic()
            connp = get_conn(db_path)
            try:
                if p.total and p.total > 0:
                    pct = int(p.downloaded * 100 / p.total)
                    if pct == last_pct and (now - last_emit_ts) < 1.0:
                        return
                    last_pct = pct
                    last_emit_ts = now
                    repo.update_progress(
                        connp,
                        job_id=job_id,
                        current=pct,
                        total=100,
                        message=f"download {m.hf_filename}",
                    )
                else:
                    if (now - last_emit_ts) < 2.0:
                        return
                    last_emit_ts = now
                    repo.update_progress(
                        connp,
                        job_id=job_id,
                        current=0,
                        total=100,
                        message=f"download {m.hf_filename}",
                    )
            finally:
                connp.close()

        last_pct = -1
        last_emit_ts = 0.0
        try:
            download_with_resume(
                url=url,
                out_path=out_path,
                on_progress=on_prog,
                should_cancel=lambda: cancel.is_set(),
            )
        except DownloadCancelled:
            # Allow runner to mark this job cancelled.
            return

        # Mark complete only after a successful full download.
        marker = get_local_model_complete_marker(model_id=model_id_norm)
        atomic_write_text(marker, "ok\n")

        # Cleanup any previously downloaded models not in our supported list.
        gguf_root = get_models_dir() / "gguf"
        keep_files: set[Path] = set()
        keep_markers: set[Path] = set()
        for choice in LOCAL_MODELS:
            mp = get_local_model_path(model_id=choice.id)
            keep_files.add(mp.resolve())
            keep_markers.add(
                get_local_model_complete_marker(model_id=choice.id).resolve()
            )

        for p in gguf_root.rglob("*.gguf"):
            try:
                if p.resolve() not in keep_files:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        for p in gguf_root.rglob("*.complete"):
            try:
                if p.resolve() not in keep_markers:
                    p.unlink(missing_ok=True)
            except Exception:
                pass

        conn3 = get_conn(db_path)
        try:
            repo.add_event(
                conn3,
                job_id=job_id,
                level="info",
                text=f"engine: {inst.llama_cli_path}",
            )
            repo.add_event(
                conn3, job_id=job_id, level="info", text=f"model: {out_path}"
            )
            repo.update_progress(
                conn3, job_id=job_id, current=100, total=100, message="installed"
            )
        finally:
            conn3.close()

    return run
