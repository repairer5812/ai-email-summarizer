from __future__ import annotations

import json
import time
import sqlite3
from datetime import datetime, timezone

import keyring
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.jobs.runner import get_runner
from webmail_summary.jobs.tasks_sync import sync_mailbox_task
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.jobs.tasks_local_install import local_install_task
from webmail_summary.llm.local_models import get_local_model, recommend_local_model
from webmail_summary.llm.local_status import check_local_ready, delete_gguf_and_marker
from webmail_summary.llm.local_status import (
    get_local_model_complete_marker,
    get_local_model_path,
    get_gguf_path_for_repo_file,
)
from webmail_summary.llm.provider import LlmNotReady
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs.tasks_resummarize import resummarize_day_task
from webmail_summary.jobs.worker_probe import is_sync_worker_running, kill_sync_worker


router = APIRouter(prefix="/api")


def _db_path():
    return get_app_data_dir() / "db.sqlite3"


def _job_age_seconds(updated_at: str) -> float:
    try:
        ts = datetime.fromisoformat(str(updated_at))
        now = datetime.now(timezone.utc)
        return max(0.0, (now - ts).total_seconds())
    except Exception:
        return 0.0


def _is_stale_active_sync_job(job: repo.JobRow) -> tuple[bool, str]:
    age_s = _job_age_seconds(job.updated_at)
    status = str(job.status or "").strip().lower()
    worker_alive = False
    try:
        worker_alive = is_sync_worker_running(job_id=job.id)
    except Exception:
        worker_alive = False

    if status == "queued" and age_s > 120:
        return True, "stale queued job (no transition for 120s)"
    if status == "cancel_requested" and not worker_alive and age_s > 20:
        return True, "stale cancel_requested job (worker not running)"
    if status == "running" and not worker_alive and age_s > 45:
        return True, "stale running job (worker not running)"
    if age_s > 60 * 30:
        return True, "stale job (no updates for 30m)"
    return False, ""


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
            stale, stale_reason = _is_stale_active_sync_job(active)
            if not stale:
                return {"job_id": active.id, "already_running": True}
            try:
                kill_sync_worker(job_id=str(active.id))
            except Exception:
                pass
            repo.set_job_status(
                conn0,
                job_id=active.id,
                status="failed",
                message=stale_reason,
            )
    finally:
        conn0.close()

    # Preflight AI readiness so users immediately see a clear reason.
    connp = get_conn(_db_path())
    try:
        s = load_settings(connp)
    finally:
        connp.close()

    detail: dict[str, object] = {
        "backend": (s.llm_backend or "").strip().lower(),
    }
    err_msg = ""
    if detail["backend"] == "local":
        ready = check_local_ready(model_id=s.local_model_id)
        detail["model_id"] = s.local_model_id
        detail["engine_ok"] = bool(ready.engine_ok)
        detail["engine_path"] = ready.engine_path
        detail["model_ok"] = bool(ready.model_ok)
        detail["expected_model_path"] = str(
            get_local_model_path(model_id=s.local_model_id)
        )
        detail["expected_marker_path"] = str(
            get_local_model_complete_marker(model_id=s.local_model_id)
        )
        if not ready.engine_ok:
            err_msg = "Local engine not installed"
        elif not ready.model_ok:
            err_msg = "Local model not installed"
    elif detail["backend"] in {"openrouter", "cloud"}:
        provider_name = (s.cloud_provider or "openai").strip().lower()
        detail["provider"] = provider_name
        api_key = ""
        try:
            api_key = (
                keyring.get_password(f"webmail-summary::{provider_name}", "api_key")
                or ""
            )
        except Exception:
            api_key = ""
        if not api_key.strip():
            err_msg = f"{provider_name.upper()} API key not set in setup"
    else:
        err_msg = f"Unsupported LLM backend: {detail['backend']}"

    if err_msg:
        return JSONResponse(
            {
                "error": "llm_not_ready",
                "message": str(LlmNotReady(err_msg)),
                "detail": detail,
            },
            status_code=409,
        )

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

    # Always enqueue the job so the engine can be auto-upgraded to latest.
    # The job itself will skip download if the model is already present.
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


@router.post("/jobs/refresh-overviews")
async def start_refresh_overviews(request: Request):
    try:
        payload = {}
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        date_keys = payload.get("date_keys")
        force_refresh = bool(payload.get("force_refresh", False))
        from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_task

        job_id = get_runner().enqueue(
            kind="refresh-overviews",
            fn=refresh_overviews_task(
                date_keys=date_keys,
                force_refresh=force_refresh,
            ),
        )
        return {"job_id": job_id}
    except (ImportError, ModuleNotFoundError):
        return JSONResponse({"error": "not implemented"}, status_code=501)
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            return JSONResponse({"error": "database busy"}, status_code=503)
        raise


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    conn = get_conn(_db_path())
    try:
        job = repo.get_job(conn, job_id)
        if (
            job is not None
            and job.kind == "sync"
            and job.status
            in {
                "queued",
                "running",
                "cancel_requested",
            }
        ):
            stale, stale_reason = _is_stale_active_sync_job(job)
            if stale:
                final_status = (
                    "cancelled" if job.status == "cancel_requested" else "failed"
                )
                repo.add_event(
                    conn,
                    job_id=job.id,
                    level="warn",
                    text=stale_reason,
                )
                repo.set_job_status(
                    conn,
                    job_id=job.id,
                    status=final_status,
                    message=stale_reason,
                )
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
                "created_at": job.created_at,
                "updated_at": job.updated_at,
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


@router.get("/local/models")
def list_local_models():
    """Return all local models with their installation status."""
    from webmail_summary.llm.local_models import LOCAL_MODELS

    result: list[dict] = []
    for m in LOCAL_MODELS:
        mp = get_gguf_path_for_repo_file(hf_repo_id=m.hf_repo_id, hf_filename=m.hf_filename)
        marker = mp.parent / (mp.name + ".complete")
        installed = mp.exists() and mp.is_file() and marker.exists()
        size_bytes = int(mp.stat().st_size) if installed and mp.exists() else 0
        result.append(
            {
                "id": m.id,
                "label": m.label,
                "group": m.group,
                "hf_repo_id": m.hf_repo_id,
                "hf_filename": m.hf_filename,
                "installed": installed,
                "size_bytes": size_bytes,
            }
        )
    return {"models": result}


@router.delete("/local/models/{model_id}")
def delete_local_model(model_id: str):
    """Delete a downloaded local model's GGUF file and marker."""
    m = get_local_model(model_id)

    mp = get_gguf_path_for_repo_file(hf_repo_id=m.hf_repo_id, hf_filename=m.hf_filename)
    marker = mp.parent / (mp.name + ".complete")
    if not mp.exists() and not marker.exists():
        return JSONResponse({"error": "model not installed"}, status_code=404)

    delete_gguf_and_marker(hf_repo_id=m.hf_repo_id, hf_filename=m.hf_filename)
    return {"ok": True, "model_id": m.id}
