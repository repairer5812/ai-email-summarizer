"""MLX install failures must fail the job instead of being recorded as success."""

from __future__ import annotations

import subprocess
import threading
import time
from types import SimpleNamespace

from webmail_summary.index.db import app_db_path, init_db, open_db
from webmail_summary.jobs import repo
from webmail_summary.jobs import tasks_local_install as install
from webmail_summary.jobs.runner import JobRunner
from webmail_summary.llm.local_models import LocalModelChoice
from webmail_summary.llm.mlx_engine import MlxInstall


def _mlx_model() -> LocalModelChoice:
    return LocalModelChoice(
        id="mlx_probe",
        label="MLX probe",
        tier="fast",
        hf_repo_id="org/mlx-probe",
        hf_filename="model",
        notes="",
        engine="mlx",
    )


class _Proc:
    def __init__(self, *, alive: bool) -> None:
        self._alive = alive
        self.terminated = False

    def poll(self):
        return None if self._alive else 1

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def kill(self) -> None:
        self._alive = False

    def wait(self, timeout=None):
        return 0


def _patch_mlx(monkeypatch, proc: _Proc) -> None:
    real_popen = subprocess.Popen

    def popen(cmd, *args, **kwargs):
        rendered = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)
        if "mlx_lm.server" in rendered:
            return proc
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(install, "get_local_model", lambda model_id: _mlx_model())
    monkeypatch.setattr(
        "webmail_summary.llm.mlx_status.check_mlx_ready",
        lambda model_id: SimpleNamespace(mlx_installed=False, model_cached=False),
    )
    monkeypatch.setattr(
        "webmail_summary.llm.mlx_engine.ensure_mlx_installed",
        lambda: MlxInstall(python="python", server_cmd=["python", "-m", "mlx_lm.server"]),
    )
    monkeypatch.setattr(subprocess, "Popen", popen)


def _wait_status(job_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    status = ""
    while time.monotonic() < deadline:
        with open_db(app_db_path()) as conn:
            job = repo.get_job(conn, job_id)
            status = str(job.status if job else "")
        if status in {"succeeded", "failed", "cancelled"}:
            return status
        time.sleep(0.02)
    return status


def test_mlx_install_dead_server_marks_job_failed(monkeypatch):
    init_db(app_db_path())
    _patch_mlx(monkeypatch, _Proc(alive=False))
    runner = JobRunner()
    job_id = runner.enqueue(
        kind="local-install",
        fn=install.local_install_task(model_id="mlx_probe"),
    )

    assert _wait_status(job_id) == "failed"
    with open_db(app_db_path()) as conn:
        job = repo.get_job(conn, job_id)
        assert job is not None
        assert "MLX model download/load failed" in job.message


def test_mlx_install_http_error_raises(monkeypatch):
    init_db(app_db_path())
    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="job-mlx", kind="local-install")
    clock = {"t": 0.0}

    def monotonic():
        return clock["t"]

    def sleep(seconds):
        clock["t"] += float(seconds)

    monkeypatch.setattr(install.time, "monotonic", monotonic)
    monkeypatch.setattr(install.time, "sleep", sleep)
    _patch_mlx(monkeypatch, _Proc(alive=True))
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=500),
    )

    try:
        install._run_mlx_install("job-mlx", threading.Event(), "mlx_probe")
    except RuntimeError as exc:
        assert str(exc) == "MLX model download/load failed"
    else:
        raise AssertionError("HTTP 500 was treated as a finished install")


def test_mlx_install_cancel_returns_without_error(monkeypatch):
    init_db(app_db_path())
    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="job-mlx-cancel", kind="local-install")
    proc = _Proc(alive=True)
    cancel = threading.Event()

    real_popen = subprocess.Popen

    def popen(cmd, *args, **kwargs):
        rendered = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)
        if "mlx_lm.server" in rendered:
            cancel.set()
            return proc
        return real_popen(cmd, *args, **kwargs)

    _patch_mlx(monkeypatch, proc)
    monkeypatch.setattr(subprocess, "Popen", popen)

    install._run_mlx_install("job-mlx-cancel", cancel, "mlx_probe")

    assert proc.terminated is True
