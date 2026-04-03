from __future__ import annotations

import json
from datetime import datetime, timezone

import keyring
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from webmail_summary.imap_client import ImapSession
from webmail_summary.index.settings import _normalize_ui_theme, load_settings
from webmail_summary.llm.local_models import LOCAL_MODELS, get_local_model
from webmail_summary.llm.local_status import check_local_ready
from webmail_summary.ui.settings_gateway import db_path, set_setting
from webmail_summary.ui.setup_service import get_cloud_keys
from webmail_summary.ui.setup_service import pick_directory_dialog
from webmail_summary.ui.setup_service import test_cloud_api_key
from webmail_summary.ui.updates import _DEFAULT_UPDATE_REPO, _get_app_version
from webmail_summary.ui.web_shared import get_active_jobs, templates

router = APIRouter()


def _is_auth_error(msg: str) -> bool:
    m = (msg or "").lower()
    needles = [
        "authenticationfailed",
        "auth failed",
        "invalid credentials",
        "login failed",
        "authentication failure",
        "authenticat",
        "invalid login",
    ]
    return any(n in m for n in needles)


@router.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request):
    from webmail_summary.index.db import get_conn

    tab = str(request.query_params.get("tab") or "profile")

    conn = get_conn(db_path())
    try:
        settings = load_settings(conn)
        active_jobs = get_active_jobs(conn)

        provider_name = (settings.cloud_provider or "openai").strip().lower()
        cloud_keys = get_cloud_keys()

        local_ready = check_local_ready(model_id=settings.local_model_id)
        imap_pass_set = False
        if settings.imap_host and settings.imap_user:
            try:
                svc = f"webmail-summary::{settings.imap_host}"
                val = keyring.get_password(svc, settings.imap_user)
                imap_pass_set = bool(val and val.strip())
            except Exception:
                pass

        ctx = {
            "request": request,
            "theme": settings.ui_theme,
            "current_tab": tab,
            "imap_pass_set": imap_pass_set,
            "defaults": {
                "imap_host": settings.imap_host or "imap.daouoffice.com",
                "imap_port": str(settings.imap_port) or "993",
                "imap_user": settings.imap_user or "",
                "imap_folder": settings.imap_folder or "INBOX",
                "sender_filter": settings.sender_filter or "",
                "obsidian_root": settings.obsidian_root or "",
                "llm_backend": settings.llm_backend,
                "cloud_provider": provider_name,
                "cloud_multimodal_enabled": settings.cloud_multimodal_enabled,
                "local_model_id": settings.local_model_id,
                "openrouter_model": settings.openrouter_model,
                "external_max_bytes": str(settings.external_max_bytes),
                "revert_seen": settings.revert_seen_after_sync,
                "user_roles": settings.user_roles,
                "user_interests": settings.user_interests,
                "ui_theme": settings.ui_theme,
                "close_behavior": settings.close_behavior,
                "app_version": _get_app_version(),
                "update_channel": settings.update_channel,
                "update_latest_version": settings.update_latest_version,
                "update_auto_check_enabled": settings.update_auto_check_enabled,
                "update_repo": settings.update_repo,
                "update_snooze_until": settings.update_snooze_until,
                "update_skip_version": settings.update_skip_version,
                "update_last_checked_at": settings.update_last_checked_at,
                "update_download_url": settings.update_download_url,
                "update_last_check_status": settings.update_last_check_status,
            },
            "active": active_jobs,
            "cloud": {
                "key_set": cloud_keys.get(provider_name, False),
                "cloud_cloud_keys": cloud_keys,
            },
            "local_models": LOCAL_MODELS,
            "local_ready": {
                "engine_ok": local_ready.engine_ok,
                "model_ok": local_ready.model_ok,
            },
        }
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="setup.html", context=ctx)


@router.post("/setup/test-imap")
def setup_test_imap(
    imap_host: str = Form(""),
    imap_port: str = Form(""),
    imap_user: str = Form(""),
    imap_password: str = Form(""),
):
    from webmail_summary.index.db import get_conn

    host = (imap_host or "").strip()
    user = (imap_user or "").strip()
    port_raw = (imap_port or "").strip()
    pw_input = str(imap_password or "")

    if not host:
        return JSONResponse(
            {"ok": False, "kind": "input", "message": "IMAP 호스트를 입력하세요."}
        )
    if not user:
        return JSONResponse(
            {"ok": False, "kind": "input", "message": "IMAP 계정(아이디)을 입력하세요."}
        )

    try:
        port = int(port_raw or "993")
    except Exception:
        return JSONResponse(
            {"ok": False, "kind": "input", "message": "IMAP 포트가 올바르지 않습니다."}
        )

    service = f"webmail-summary::{host}"
    pw = pw_input.strip()
    if not pw:
        try:
            pw = (keyring.get_password(service, user) or "").strip()
        except Exception:
            pw = ""

    if not pw:
        return JSONResponse(
            {
                "ok": False,
                "kind": "input",
                "message": "비밀번호가 비어 있습니다. 비밀번호를 입력하거나 먼저 저장해주세요.",
            }
        )

    conn = get_conn(db_path())
    try:
        set_setting(conn, "imap_host", host)
        set_setting(conn, "imap_port", str(port))
        set_setting(conn, "imap_user", user)
        conn.commit()
    finally:
        conn.close()

    folders: list[str] = []
    try:
        with ImapSession(host, int(port), user, pw) as imap:
            folders = imap.list_folders()
    except Exception as e:
        msg = str(e)
        if _is_auth_error(msg) or e.__class__.__name__.lower() in {
            "loginerror",
            "authenticationerror",
        }:
            return JSONResponse(
                {
                    "ok": False,
                    "kind": "auth",
                    "message": "비밀번호가 틀렸거나 로그인이 거부되었습니다. 아이디/비밀번호를 다시 확인해주세요.",
                }
            )
        return JSONResponse(
            {
                "ok": False,
                "kind": "network",
                "message": f"연결 실패: {msg[:160]}",
            }
        )

    if pw_input.strip():
        keyring.set_password(service, user, pw_input.strip())

    return JSONResponse(
        {"ok": True, "kind": "ok", "message": "연결 성공", "folders": folders}
    )


@router.post("/setup/test-cloud-key")
def setup_test_cloud_key(
    cloud_provider: str = Form("openai"),
    openrouter_model: str = Form(""),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    google_api_key: str = Form(""),
    upstage_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
):
    provider = (cloud_provider or "openai").strip().lower()
    model = (openrouter_model or "").strip()

    keys = {
        "openai": openai_api_key,
        "anthropic": anthropic_api_key,
        "google": google_api_key,
        "upstage": upstage_api_key,
        "openrouter": openrouter_api_key,
    }

    candidate = (keys.get(provider, "") or "").strip()
    if not candidate:
        try:
            candidate = (
                keyring.get_password(f"webmail-summary::{provider}", "api_key") or ""
            ).strip()
        except Exception:
            candidate = ""

    if not candidate:
        return JSONResponse(
            {
                "ok": False,
                "message": "실패: API 키가 비어 있습니다. 입력하거나 저장된 키를 확인하세요.",
            }
        )

    ok, msg = test_cloud_api_key(provider, candidate, model)
    return JSONResponse({"ok": ok, "message": msg})


@router.post("/setup/save", response_class=HTMLResponse)
def setup_save(
    imap_host: str = Form(""),
    imap_port: str = Form("993"),
    imap_user: str = Form(""),
    imap_folder: str = Form("INBOX"),
    sender_filter: str = Form(""),
    obsidian_root: str = Form(""),
    llm_backend: str = Form("local"),
    local_model_id: str = Form("fast"),
    cloud_provider: str = Form("openai"),
    cloud_multimodal_enabled: str = Form("0"),
    openrouter_model: str = Form(""),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    google_api_key: str = Form(""),
    upstage_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
    external_max_bytes: str = Form(""),
    revert_seen_after_sync: str = Form("0"),
    user_roles: list[str] = Form([]),
    user_interests: str = Form(""),
    update_channel: str = Form("stable"),
    update_latest_version: str = Form(""),
    update_auto_check_enabled: str = Form("0"),
    update_snooze_until: str = Form(""),
    update_skip_version: str = Form(""),
    update_last_checked_at: str = Form(""),
    update_download_url: str = Form(""),
    ui_theme: str | None = Form(None),
    close_behavior: str = Form("background"),
    current_tab: str = Form("profile"),
):
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        if imap_host:
            set_setting(conn, "imap_host", imap_host)
        if imap_port:
            set_setting(conn, "imap_port", imap_port)
        if imap_user:
            set_setting(conn, "imap_user", imap_user)
        if imap_folder:
            set_setting(conn, "imap_folder", imap_folder)
        set_setting(conn, "sender_filter", (sender_filter or "").strip())
        if obsidian_root:
            set_setting(conn, "obsidian_root", obsidian_root)
        if llm_backend:
            set_setting(conn, "llm_backend", llm_backend.strip().lower())
        if cloud_provider:
            set_setting(conn, "cloud_provider", cloud_provider.strip().lower())
        set_setting(
            conn,
            "cloud_multimodal_enabled",
            "1"
            if (cloud_multimodal_enabled or "").strip().lower()
            in {"1", "on", "true", "yes"}
            else "0",
        )
        if local_model_id:
            set_setting(
                conn,
                "local_model_id",
                get_local_model(local_model_id.strip().lower()).id,
            )
        if openrouter_model:
            set_setting(conn, "openrouter_model", openrouter_model.strip())
        if external_max_bytes:
            set_setting(conn, "external_max_bytes", external_max_bytes.strip())
        if ui_theme is not None and str(ui_theme).strip():
            set_setting(conn, "ui_theme", _normalize_ui_theme(ui_theme))

        cb = (close_behavior or "background").strip().lower()
        if cb not in {"background", "exit"}:
            cb = "background"
        set_setting(conn, "close_behavior", cb)

        if user_roles:
            set_setting(conn, "user_roles", json.dumps(user_roles))
        set_setting(conn, "user_interests", user_interests)

        upd_ch = (update_channel or "stable").strip().lower()
        if upd_ch not in {"stable", "beta"}:
            upd_ch = "stable"
        set_setting(conn, "update_channel", upd_ch)
        set_setting(
            conn, "update_latest_version", (update_latest_version or "").strip()
        )
        set_setting(conn, "update_repo", _DEFAULT_UPDATE_REPO)
        set_setting(
            conn,
            "update_auto_check_enabled",
            "1"
            if (update_auto_check_enabled or "").strip().lower()
            in {"1", "on", "true", "yes"}
            else "0",
        )
        set_setting(conn, "update_snooze_until", (update_snooze_until or "").strip())
        set_setting(conn, "update_skip_version", (update_skip_version or "").strip())
        set_setting(
            conn, "update_last_checked_at", (update_last_checked_at or "").strip()
        )
        set_setting(conn, "update_download_url", (update_download_url or "").strip())

        rev = (revert_seen_after_sync or "").strip().lower()
        set_setting(
            conn,
            "revert_seen_after_sync",
            "1" if rev in {"1", "on", "true", "yes"} else "0",
        )

        set_setting(conn, "configured_at", datetime.now(timezone.utc).isoformat())
        conn.commit()
    finally:
        conn.close()

    keys_to_store = {
        "openai": openai_api_key,
        "anthropic": anthropic_api_key,
        "google": google_api_key,
        "upstage": upstage_api_key,
        "openrouter": openrouter_api_key,
    }
    for provider, val in keys_to_store.items():
        if val.strip():
            keyring.set_password(f"webmail-summary::{provider}", "api_key", val.strip())

    tabs = ["profile", "connection", "ai", "advanced"]
    try:
        idx = tabs.index(current_tab)
        if idx < len(tabs) - 1:
            return RedirectResponse(f"/setup?tab={tabs[idx + 1]}", status_code=303)
    except ValueError:
        pass

    return RedirectResponse("/?saved=1", status_code=303)


@router.post("/setup/pick-obsidian")
def setup_pick_obsidian():
    from webmail_summary.index.db import get_conn

    picked = pick_directory_dialog()
    if not picked:
        return RedirectResponse("/setup", status_code=302)

    conn = get_conn(db_path())
    try:
        set_setting(conn, "obsidian_root", picked)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/setup", status_code=302)


@router.post("/setup/save-partial")
def setup_save_partial(ui_theme: str = Form(None), llm_backend: str = Form(None)):
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        if ui_theme:
            set_setting(conn, "ui_theme", _normalize_ui_theme(ui_theme))
        if llm_backend:
            set_setting(conn, "llm_backend", llm_backend.strip().lower())
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
