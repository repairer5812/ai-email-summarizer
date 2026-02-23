from __future__ import annotations

import queue
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.jobs.worker_probe import kill_sync_worker
from webmail_summary.util.app_data import get_app_data_dir


JobFunc = Callable[[str, threading.Event], None]


@dataclass(frozen=True)
class EnqueuedJob:
    id: str
    kind: str
    fn: JobFunc


class JobRunner:
    def __init__(self) -> None:
        self._q: "queue.Queue[EnqueuedJob]" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._started = False
        self._active: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._cancelled_queued: set[str] = set()
        self._active_procs: dict[str, subprocess.Popen[str]] = {}
        self._cancelled_procs: set[str] = set()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def enqueue(self, *, kind: str, fn: JobFunc) -> str:
        self.start()
        job_id = uuid.uuid4().hex
        db_path = get_app_data_dir() / "db.sqlite3"
        conn = get_conn(db_path)
        try:
            repo.create_job(conn, job_id=job_id, kind=kind)
        finally:
            conn.close()
        self._q.put(EnqueuedJob(id=job_id, kind=kind, fn=fn))
        return job_id

    def cancel(self, job_id: str) -> bool:
        jid = str(job_id)
        with self._lock:
            proc = self._active_procs.get(jid)
            if proc is not None:
                self._cancelled_procs.add(jid)
                try:
                    proc.terminate()
                except Exception:
                    pass
                # Best-effort: on Windows, also kill the whole process tree.
                if sys.platform == "win32":
                    try:
                        subprocess.run(
                            [
                                "taskkill",
                                "/PID",
                                str(int(proc.pid)),
                                "/T",
                                "/F",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    except Exception:
                        pass
                return True
            ev = self._active.get(jid)
            if ev is not None:
                ev.set()
                return True
            # If job hasn't started yet, remember the cancellation.
            self._cancelled_queued.add(jid)

        # Fallback: if runner lost track of the subprocess, try to find/kill it.
        try:
            kill_sync_worker(job_id=jid)
        except Exception:
            pass
        return True

    def _loop(self) -> None:
        db_path = get_app_data_dir() / "db.sqlite3"
        while True:
            job = self._q.get()
            cancel = threading.Event()

            with self._lock:
                if job.id in self._cancelled_queued:
                    self._cancelled_queued.discard(job.id)
                    connx = get_conn(db_path)
                    try:
                        repo.set_job_status(connx, job_id=job.id, status="cancelled")
                        repo.add_event(
                            connx,
                            job_id=job.id,
                            level="info",
                            text="cancelled before start",
                        )
                    finally:
                        connx.close()
                    continue

                self._active[job.id] = cancel

            conn = get_conn(db_path)
            try:
                repo.set_job_status(conn, job_id=job.id, status="running")
                repo.add_event(
                    conn, job_id=job.id, level="info", text=f"start {job.kind}"
                )
            finally:
                conn.close()

            try:
                if job.kind == "sync":
                    # Run sync in a separate process so cancel can stop immediately.
                    cmd = [
                        sys.executable,
                        "-m",
                        "webmail_summary.jobs.worker_sync",
                        "--job-id",
                        job.id,
                    ]
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    with self._lock:
                        self._active_procs[job.id] = proc
                    rc = proc.wait()
                    with self._lock:
                        cancelled = job.id in self._cancelled_procs
                    if cancelled:
                        # Finalize cancelled state only after the worker has stopped.
                        connc = get_conn(db_path)
                        try:
                            cur = repo.get_job(connc, job.id)
                            if cur is not None and cur.status == "cancel_requested":
                                repo.add_event(
                                    connc,
                                    job_id=job.id,
                                    level="info",
                                    text="cancelled",
                                )
                                repo.set_job_status(
                                    connc, job_id=job.id, status="cancelled"
                                )
                        finally:
                            connc.close()
                    if rc != 0 and not cancelled:
                        raise RuntimeError(f"sync worker failed: exit {rc}")
                else:
                    job.fn(job.id, cancel)
            except Exception as e:
                conn2 = get_conn(db_path)
                try:
                    repo.add_event(conn2, job_id=job.id, level="error", text=str(e))
                    cur = repo.get_job(conn2, job.id)
                    if cancel.is_set() or (
                        cur is not None and cur.status in {"cancelled"}
                    ):
                        # Preserve cancelled state; cancellation can look like an error
                        # (e.g. terminated subprocess).
                        pass
                    else:
                        repo.set_job_status(
                            conn2, job_id=job.id, status="failed", message=str(e)
                        )
                finally:
                    conn2.close()
            else:
                conn3 = get_conn(db_path)
                try:
                    if cancel.is_set():
                        repo.set_job_status(conn3, job_id=job.id, status="cancelled")
                    else:
                        # sync worker will set succeeded itself
                        if job.kind != "sync":
                            repo.set_job_status(
                                conn3, job_id=job.id, status="succeeded"
                            )
                finally:
                    conn3.close()
            finally:
                with self._lock:
                    self._active.pop(job.id, None)
                    self._active_procs.pop(job.id, None)
                    self._cancelled_procs.discard(job.id)


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
