from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from webmail_summary.llm.local_engine import find_llama_cpp_installed
from webmail_summary.llm.local_models import get_local_model
from webmail_summary.util.app_data import get_models_dir


@dataclass(frozen=True)
class LocalReady:
    engine_ok: bool
    model_ok: bool
    engine_path: str | None
    model_path: str | None


def get_local_model_path(*, model_id: str) -> Path:
    m = get_local_model(model_id)
    safe_repo = m.hf_repo_id.replace("/", "__")
    return get_models_dir() / "gguf" / safe_repo / m.hf_filename


def get_local_model_complete_marker(*, model_id: str) -> Path:
    mp = get_local_model_path(model_id=model_id)
    return mp.parent / (mp.name + ".complete")


def get_gguf_path_for_repo_file(*, hf_repo_id: str, hf_filename: str) -> Path:
    safe_repo = str(hf_repo_id).replace("/", "__")
    return get_models_dir() / "gguf" / safe_repo / str(hf_filename)


def delete_gguf_and_marker(*, hf_repo_id: str, hf_filename: str) -> None:
    mp = get_gguf_path_for_repo_file(hf_repo_id=hf_repo_id, hf_filename=hf_filename)
    marker = mp.parent / (mp.name + ".complete")
    try:
        mp.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        marker.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        # Remove empty directory if possible.
        if mp.parent.exists() and mp.parent.is_dir():
            next(mp.parent.iterdir())
    except StopIteration:
        try:
            mp.parent.rmdir()
        except Exception:
            pass


def check_local_ready(*, model_id: str) -> LocalReady:
    try:
        inst = find_llama_cpp_installed()
        engine_ok = bool(inst and inst.llama_cli_path.exists())
        engine_path = str(inst.llama_cli_path) if inst else None
    except Exception:
        engine_ok = False
        engine_path = None

    mp = get_local_model_path(model_id=model_id)
    complete = get_local_model_complete_marker(model_id=model_id)
    model_ok = mp.exists() and mp.is_file() and complete.exists() and complete.is_file()
    return LocalReady(
        engine_ok=engine_ok,
        model_ok=model_ok,
        engine_path=engine_path,
        model_path=str(mp) if model_ok else None,
    )
