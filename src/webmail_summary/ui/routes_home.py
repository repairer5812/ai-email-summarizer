from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webmail_summary.index.mail_repo import get_daily_overview
from webmail_summary.index.settings import load_settings, set_setting
from webmail_summary.jobs.tasks_resummarize import _needs_resummarize
from webmail_summary.llm.local_status import check_local_ready, get_gguf_path_for_repo_file
from webmail_summary.ui.settings_gateway import db_path, get_setting
from webmail_summary.ui.setup_service import (
    get_cloud_keys,
    is_ai_ready,
    is_setup_complete,
)
from webmail_summary.ui.timefmt import format_date_with_weekday_ko
from webmail_summary.ui.updates import _build_update_state, _check_github_release
from webmail_summary.ui.web_shared import get_active_jobs, templates

router = APIRouter()


def _build_day_cards(conn, *, limit: int = 90) -> list[dict]:
    rows_days = list(
        conn.execute(
            "SELECT substr(internal_date, 1, 10) AS day, COUNT(*) "
            "FROM messages "
            "WHERE internal_date IS NOT NULL AND length(internal_date) >= 10 "
            "GROUP BY day ORDER BY day DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    )
    day_keys = [str(r[0] or "") for r in rows_days if str(r[0] or "").strip()]
    failed_by_day: dict[str, int] = {}
    if day_keys:
        qmarks = ",".join(["?"] * len(day_keys))
        rows_summaries = conn.execute(
            "SELECT substr(internal_date, 1, 10) AS day, summary "
            "FROM messages "
            "WHERE internal_date IS NOT NULL "
            f"AND substr(internal_date, 1, 10) IN ({qmarks})",
            tuple(day_keys),
        ).fetchall()
        for r in rows_summaries:
            day = str(r[0] or "")
            if day and _needs_resummarize(str(r[1] or "")):
                failed_by_day[day] = int(failed_by_day.get(day, 0)) + 1

    return [
        {
            "day": day,
            "day_display": format_date_with_weekday_ko(day),
            "count": int(r[1] or 0),
            "overview": get_daily_overview(conn, day),
            "failed_count": int(failed_by_day.get(day, 0)),
        }
        for r in rows_days
        for day in [str(r[0] or "")]
    ]


def _check_model_migration(settings) -> dict | None:
    """Check if the user needs to migrate from an old default model to a new one."""
    if settings.llm_backend != "local":
        return None
    from webmail_summary.llm.local_models import (
        MIGRATION_FALLBACKS,
        get_local_model,
    )

    model = get_local_model(settings.local_model_id)
    fallback_id = MIGRATION_FALLBACKS.get(model.id)
    if not fallback_id:
        return None

    # Check if the new model is NOT installed but the old one IS installed.
    new_path = get_gguf_path_for_repo_file(
        hf_repo_id=model.hf_repo_id, hf_filename=model.hf_filename
    )
    new_marker = new_path.parent / (new_path.name + ".complete")
    new_installed = new_path.exists() and new_marker.exists()
    if new_installed:
        return None  # already migrated

    old = get_local_model(fallback_id)
    old_path = get_gguf_path_for_repo_file(
        hf_repo_id=old.hf_repo_id, hf_filename=old.hf_filename
    )
    old_marker = old_path.parent / (old_path.name + ".complete")
    old_installed = old_path.exists() and old_marker.exists()
    if not old_installed:
        return None  # neither installed, normal setup flow handles this

    old_size = int(old_path.stat().st_size) if old_path.exists() else 0
    return {
        "needed": True,
        "new_model_id": model.id,
        "new_label": model.label,
        "old_model_id": old.id,
        "old_label": old.label,
        "old_size_mb": old_size // (1024 * 1024),
    }


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        settings = load_settings(conn)
        configured = get_setting(conn, "imap_host") is not None
        active_jobs = get_active_jobs(conn)

        if not configured:
            return RedirectResponse("/setup", status_code=302)

        ai_ready = is_ai_ready(settings)
        setup_complete = is_setup_complete(settings)
        local_ready = check_local_ready(model_id=settings.local_model_id)
        ai_not_ready_reason = ""
        if settings.llm_backend == "local":
            if not local_ready.engine_ok:
                ai_not_ready_reason = "AI 엔진이 설치되지 않았습니다. 아래 '설정' 버튼을 누른 뒤, AI 탭에서 '엔진 + 모델 설치' 버튼을 클릭해주세요."
            elif not local_ready.model_ok:
                ai_not_ready_reason = "AI 모델이 아직 설치되지 않았습니다. 아래 '설정' 버튼을 누른 뒤, AI 탭에서 '엔진 + 모델 설치' 버튼을 클릭해주세요."
        elif settings.llm_backend in {"openrouter", "cloud"}:
            provider_name = (settings.cloud_provider or "openai").strip().lower()
            cloud_keys = get_cloud_keys()
            if not cloud_keys.get(provider_name, False):
                ai_not_ready_reason = (
                    f"{provider_name.upper()} API 키가 설정되지 않았습니다."
                )

        provider_name = (settings.cloud_provider or "openai").strip().lower()
        cloud_keys = get_cloud_keys()

        _check_github_release(conn, settings, force=False)
        settings = load_settings(conn)
        update_state = _build_update_state(settings)

        day_cards = _build_day_cards(conn, limit=90)
    finally:
        conn.close()

    saved = str(request.query_params.get("saved") or "").strip() in {"1", "true", "yes"}
    update_checked = (
        str(request.query_params.get("update_checked") or "").strip().lower()
    )
    if update_checked not in {"latest", "available", "error"}:
        update_checked = ""
    ui_notice = str(request.query_params.get("ui_notice") or "").strip().lower()
    ui_reason = str(request.query_params.get("ui_reason") or "").strip()
    ui_report = str(request.query_params.get("ui_report") or "").strip()
    startup_notice = None
    if ui_notice == "native_fallback":
        from webmail_summary.util.app_data import get_app_data_dir

        startup_notice = {
            "kind": "warn",
            "reason": ui_reason,
            "log_path": str(get_app_data_dir() / "logs" / "ui_start.log"),
            "report_path": ui_report,
        }

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "request": request,
            "theme": settings.ui_theme,
            "days": day_cards,
            "flash": {
                "saved": saved,
                "update_checked": update_checked,
                "startup_notice": startup_notice,
            },
            "active": active_jobs,
            "update": update_state,
            "ai": {
                "ready": ai_ready,
                "setup_complete": setup_complete,
                "backend": settings.llm_backend,
                "cloud_key_set": cloud_keys.get(provider_name, False),
                "cloud_provider": provider_name,
                "cloud_cloud_keys": cloud_keys,
                "local": {
                    "model_id": settings.local_model_id,
                    "engine": getattr(settings, "local_engine", "auto"),
                    "engine_ok": local_ready.engine_ok,
                    "model_ok": local_ready.model_ok,
                },
                "not_ready_reason": ai_not_ready_reason,
            },
            "show_new_models_popup": (
                not settings.new_models_v2_dismissed
                and settings.llm_backend == "local"
            ),
            "migration": _check_model_migration(settings),
        },
    )


@router.get("/api/ui/days")
def api_get_days():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        return _build_day_cards(conn, limit=90)
    finally:
        conn.close()


@router.post("/api/new-models-popup/dismiss")
def dismiss_new_models_popup():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        set_setting(conn, "new_models_v2_dismissed", "1")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
