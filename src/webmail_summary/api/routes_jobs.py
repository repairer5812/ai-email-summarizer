from __future__ import annotations

import json
import time
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.jobs.runner import get_runner
from webmail_summary.jobs.tasks_sync import sync_mailbox_task
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.jobs.tasks_local_install import local_install_task
from webmail_summary.llm.local_models import get_local_model, recommend_local_model
from webmail_summary.llm.local_status import check_local_ready
from webmail_summary.jobs.tasks_resummarize import resummarize_day_task
from webmail_summary.jobs.worker_probe import is_sync_worker_running, kill_sync_worker


router = APIRouter(prefix="/api")


def _db_path():
    return get_app_data_dir() / "db.sqlite3"


@router.get("/local/status")
def local_status(model_id: str = ""):
    if not model_id:
        model_id = recommend_local_model().id
    m = get_local_model(model_id)
    ready = check_local_ready(model_id=model_id)
    return {
        "model_id": m.id,
        "hf_repo_id": m.hf_repo_id,
        "hf_filename": m.hf_filename,
        "engine_ok": ready.engine_ok,
        "model_ok": ready.model_ok,
        "engine_path": ready.engine_path,
        "model_path": ready.model_path,
    }


@router.post("/jobs/sync")
def start_sync():
    # Avoid piling up sync jobs if one is already running.
    conn0 = get_conn(_db_path())
    try:
        active = repo.find_active_job(conn0, kind="sync")
        if active is not None:
            # If a job has been "active" but not updated for a long time,
            # treat it as stale so users can recover.
            try:
                ts = datetime.fromisoformat(active.updated_at)
                now = datetime.now(timezone.utc)
                age_s = (now - ts).total_seconds()
            except Exception:
                age_s = 0
            if age_s <= 60 * 30:
                return {"job_id": active.id, "already_running": True}
            repo.set_job_status(
                conn0,
                job_id=active.id,
                status="failed",
                message="stale job (no updates for 30m)",
            )
    finally:
        conn0.close()

    try:
        job_id = get_runner().enqueue(kind="sync", fn=sync_mailbox_task())
        return {"job_id": job_id}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            return JSONResponse(
                {"error": "database is busy (locked). Try again in a moment."},
                status_code=503,
            )
        raise


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    ok = get_runner().cancel(job_id)

    # Update DB/UI immediately regardless of whether the worker is currently active.
    conn = get_conn(_db_path())
    try:
        job = repo.get_job(conn, job_id)
        if job is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        repo.add_event(conn, job_id=job_id, level="info", text="cancel requested")
        if job.status in {"queued"}:
            # Nothing to stop yet.
            repo.set_job_status(conn, job_id=job_id, status="cancelled")
        elif job.status in {"running"}:
            # Two-phase cancellation: request first, then finalize after worker stops.
            repo.set_job_status(conn, job_id=job_id, status="cancel_requested")
    finally:
        conn.close()

    # Best-effort: for sync jobs, force-kill worker if still running.
    try:
        connk = get_conn(_db_path())
        try:
            curk = repo.get_job(connk, job_id)
            kind = curk.kind if curk is not None else ""
        finally:
            connk.close()
        if kind == "sync":
            try:
                kill_sync_worker(job_id=str(job_id))
            except Exception:
                pass
            try:
                if not is_sync_worker_running(job_id=str(job_id)):
                    conn2 = get_conn(_db_path())
                    try:
                        cur = repo.get_job(conn2, job_id)
                        if cur is not None and cur.status == "cancel_requested":
                            repo.add_event(
                                conn2, job_id=job_id, level="info", text="cancelled"
                            )
                            repo.set_job_status(
                                conn2, job_id=job_id, status="cancelled"
                            )
                    finally:
                        conn2.close()
            except Exception:
                pass
    except Exception:
        pass

    if not ok:
        return JSONResponse({"error": "not running"}, status_code=409)
    return {"ok": True}


@router.post("/jobs/local-install")
def start_local_install(payload: dict):
    model_id = str((payload or {}).get("model_id") or "low").strip().lower()
    model_id = get_local_model(model_id).id
    try:
        conn0 = get_conn(_db_path())
        try:
            active = repo.find_active_job(conn0, kind="local-install")
            if active is not None:
                return {"job_id": active.id, "already_running": True}
        finally:
            conn0.close()

        job_id = get_runner().enqueue(
            kind="local-install", fn=local_install_task(model_id=model_id)
        )
        return {"job_id": job_id, "model_id": model_id}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            return JSONResponse(
                {"error": "database is busy (locked). Try again in a moment."},
                status_code=503,
            )
        raise


@router.post("/jobs/resummarize-day")
def start_resummarize_day(payload: dict):
    date_key = str((payload or {}).get("date_key") or "").strip()
    only_failed = bool((payload or {}).get("only_failed", True))
    message_ids_raw = (payload or {}).get("message_ids")
    message_ids: list[int] | None = None
    if isinstance(message_ids_raw, list) and message_ids_raw:
        try:
            message_ids = [int(x) for x in message_ids_raw]
        except Exception:
            return JSONResponse({"error": "message_ids must be ints"}, status_code=400)
    if not date_key:
        return JSONResponse({"error": "date_key required"}, status_code=400)

    conn0 = get_conn(_db_path())
    try:
        active = repo.find_active_job(conn0, kind="resummarize-day")
        if active is not None:
            return {"job_id": active.id, "already_running": True}
    finally:
        conn0.close()

    job_id = get_runner().enqueue(
        kind="resummarize-day",
        fn=resummarize_day_task(
            date_key=date_key, only_failed=only_failed, message_ids=message_ids
        ),
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    conn = get_conn(_db_path())
    try:
        job = repo.get_job(conn, job_id)
    finally:
        conn.close()
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "message": job.message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/jobs/{job_id}/events")
def stream_events(job_id: str):
    def gen():
        last_id = 0
        while True:
            conn = get_conn(_db_path())
            try:
                job = repo.get_job(conn, job_id)
                evs = repo.get_events_since(conn, job_id=job_id, last_id=last_id)
            finally:
                conn.close()

            if job is None:
                yield "event: error\ndata: not_found\n\n"
                return

            for r in evs:
                last_id = int(r[0])
                level = str(r[2])
                text = str(r[3])
                if level == "message_updated":
                    # text is expected to be a JSON object string.
                    yield f"event: message_updated\ndata: {text}\n\n"
                    continue
                if level == "detail":
                    # text is expected to be a JSON object string.
                    yield f"event: detail\ndata: {text}\n\n"
                    continue
                payload = {
                    "id": int(r[0]),
                    "ts": str(r[1]),
                    "level": level,
                    "text": text,
                }
                yield f"event: log\ndata: {json.dumps(payload, ensure_ascii=True)}\n\n"

            # Extract date_key if it exists in message for UI mapping
            date_key = ""
            if job.message and job.message.startswith("["):
                pot = job.message[1:11]
                if len(pot) == 10 and pot[4] == "-" and pot[7] == "-":
                    date_key = pot

            progress_payload = {
                "status": job.status,
                "current": job.progress_current,
                "total": job.progress_total,
                "message": job.message,
                "date_key": date_key,
            }
            yield f"event: progress\ndata: {json.dumps(progress_payload, ensure_ascii=True)}\n\n"

            # If a cancel was requested but the worker is already gone, finalize.
            if job.kind == "sync" and job.status == "cancel_requested":
                try:
                    if not is_sync_worker_running(job_id=str(job_id)):
                        connx = get_conn(_db_path())
                        try:
                            cur = repo.get_job(connx, job_id)
                            if cur is not None and cur.status == "cancel_requested":
                                repo.add_event(
                                    connx,
                                    job_id=job_id,
                                    level="info",
                                    text="cancelled",
                                )
                                repo.set_job_status(
                                    connx, job_id=job_id, status="cancelled"
                                )
                        finally:
                            connx.close()
                except Exception:
                    pass

            if job.status in {"succeeded", "failed", "cancelled"}:
                return
            time.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")
