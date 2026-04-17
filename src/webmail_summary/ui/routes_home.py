from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webmail_summary.index.settings import load_settings, set_setting
from webmail_summary.llm.local_status import check_local_ready
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


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    from webmail_summary.index.db import get_conn
    from webmail_summary.index.mail_repo import get_daily_overview

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
                ai_not_ready_reason = "로컬 엔진이 설치되지 않았습니다. 설정에서 로컬 모델 설치를 다시 실행하세요."
            elif not local_ready.model_ok:
                ai_not_ready_reason = "모델 파일 또는 완료 마커(.complete)를 찾지 못했습니다. 설정에서 모델 설치를 다시 실행하세요."
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

        rows_days = list(
            conn.execute(
                "SELECT substr(internal_date, 1, 10) AS day, COUNT(*) "
                "FROM messages "
                "WHERE internal_date IS NOT NULL AND length(internal_date) >= 10 "
                "GROUP BY day ORDER BY day DESC LIMIT 90"
            ).fetchall()
        )
        day_cards = [
            {
                "day": str(r[0] or ""),
                "day_display": format_date_with_weekday_ko(str(r[0] or "")),
                "count": int(r[1] or 0),
                "overview": get_daily_overview(conn, str(r[0] or "")),
            }
            for r in rows_days
        ]
    finally:
        conn.close()

    saved = str(request.query_params.get("saved") or "").strip() in {"1", "true", "yes"}
    update_checked = (
        str(request.query_params.get("update_checked") or "").strip().lower()
    )
    if update_checked not in {"latest", "available", "error"}:
        update_checked = ""

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "request": request,
            "theme": settings.ui_theme,
            "days": day_cards,
            "flash": {"saved": saved, "update_checked": update_checked},
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
                    "engine_ok": local_ready.engine_ok,
                    "model_ok": local_ready.model_ok,
                },
                "not_ready_reason": ai_not_ready_reason,
            },
            "show_new_models_popup": (
                not settings.new_models_v2_dismissed
                and settings.llm_backend == "local"
            ),
        },
    )


@router.get("/api/ui/days")
def api_get_days():
    from webmail_summary.index.db import get_conn
    from webmail_summary.index.mail_repo import get_daily_overview

    conn = get_conn(db_path())
    try:
        rows = list(
            conn.execute(
                "SELECT substr(internal_date, 1, 10) AS day, COUNT(*) "
                "FROM messages "
                "WHERE internal_date IS NOT NULL AND length(internal_date) >= 10 "
                "GROUP BY day ORDER BY day DESC LIMIT 90"
            ).fetchall()
        )
        return [
            {
                "day": str(r[0] or ""),
                "day_display": format_date_with_weekday_ko(str(r[0] or "")),
                "count": int(r[1] or 0),
                "overview": get_daily_overview(conn, str(r[0] or "")),
            }
            for r in rows
        ]
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
