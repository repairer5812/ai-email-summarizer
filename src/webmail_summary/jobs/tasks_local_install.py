from __future__ import annotations

import threading
from pathlib import Path

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.llm.hf_download import download_with_resume, hf_resolve_url
from webmail_summary.llm.local_engine import (
    EngineInstallError,
    ensure_llama_cpp_installed,
)
from webmail_summary.llm.local_models import LOCAL_MODELS, get_local_model
from webmail_summary.llm.local_status import get_local_model_path
from webmail_summary.llm.local_status import get_local_model_complete_marker
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.app_data import get_models_dir
from webmail_summary.util.atomic_io import atomic_write_text


def local_install_task(*, model_id: str):
    def run(job_id: str, cancel: threading.Event) -> None:
        db_path = get_app_data_dir() / "db.sqlite3"

        # Normalize model id.
        model_id_norm = get_local_model(model_id).id

        # 1) Ensure engine
        conn = get_conn(db_path)
        try:
            repo.update_progress(
                conn, job_id=job_id, current=0, total=100, message="install engine"
            )
        finally:
            conn.close()

        try:
            inst = ensure_llama_cpp_installed()
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
            connp = get_conn(db_path)
            try:
                if p.total and p.total > 0:
                    pct = int(p.downloaded * 100 / p.total)
                    repo.update_progress(
                        connp,
                        job_id=job_id,
                        current=pct,
                        total=100,
                        message=f"download {m.hf_filename}",
                    )
                else:
                    repo.update_progress(
                        connp,
                        job_id=job_id,
                        current=0,
                        total=100,
                        message=f"download {m.hf_filename}",
                    )
            finally:
                connp.close()

        download_with_resume(url=url, out_path=out_path, on_progress=on_prog)

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
