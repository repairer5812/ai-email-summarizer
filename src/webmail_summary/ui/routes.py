from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path

import keyring
import requests
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from packaging.version import InvalidVersion, Version

from webmail_summary.imap_client import ImapSession
from webmail_summary.index.mail_repo import (
    get_message_detail,
    list_messages_by_date,
)
from webmail_summary.index.settings import Settings, load_settings
from webmail_summary.llm.local_models import (
    LOCAL_MODELS,
    get_local_model,
)
from webmail_summary.llm.local_status import check_local_ready
from webmail_summary.ui.i18n import t as _t
from webmail_summary.ui.i18n import ui_lang as _ui_lang
from webmail_summary.ui.timefmt import format_kst, time_kst, format_date_with_weekday_ko

from webmail_summary.util.app_data import default_obsidian_root, get_app_data_dir
from webmail_summary.util.jsonish import coerce_summary_text


def _fmt_summarize_ms(ms: int | None) -> str:
    if ms is None:
        return ""
    try:
        v = int(ms)
    except Exception:
        return ""
    if v <= 0:
        return ""
    if v < 1000:
        return f"{v}ms"
    return f"{v / 1000.0:.1f}s"


router = APIRouter()

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.globals["t"] = _t
templates.env.globals["ui_lang"] = _ui_lang


def _db_path() -> Path:
    return get_app_data_dir() / "db.sqlite3"


def _get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _get_active_jobs(conn) -> dict:
    sync_row = conn.execute(
        "SELECT id, status, progress_current, progress_total, message "
        "FROM jobs WHERE kind='sync' AND status IN ('queued','running','cancel_requested') "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    resum_row = conn.execute(
        "SELECT id, status, progress_current, progress_total, message "
        "FROM jobs WHERE kind='resummarize-day' AND status IN ('queued','running','cancel_requested') "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    refresh_row = conn.execute(
        "SELECT id, status, progress_current, progress_total, message "
        "FROM jobs WHERE kind='refresh-overviews' AND status IN ('queued','running','cancel_requested') "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    install_row = conn.execute(
        "SELECT id, status, progress_current, progress_total, message "
        "FROM jobs WHERE kind='local-install' AND status IN ('queued','running','cancel_requested') "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    def _row_to_dict(row):
        if not row:
            return None
        msg = str(row[4] or "")
        date_key = ""
        # Robust extraction of [YYYY-MM-DD]
        m = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", msg)
        if m:
            date_key = m.group(1)

        return {
            "id": str(row[0]),
            "status": str(row[1] or ""),
            "current": float(row[2] or 0),
            "total": float(row[3] or 0),
            "message": msg,
            "date_key": date_key,
        }

    return {
        "sync": _row_to_dict(sync_row),
        "resummarize": _row_to_dict(resum_row),
        "refresh_overviews": _row_to_dict(refresh_row),
        "local_install": _row_to_dict(install_row),
    }


def _get_cloud_keys() -> dict[str, bool]:
    cloud_keys = {}
    for p in ["openai", "anthropic", "google", "upstage", "openrouter"]:
        try:
            svc = f"webmail-summary::{p}"
            val = keyring.get_password(svc, "api_key")
            # Loose check: must be a non-empty string.
            cloud_keys[p] = bool(val and val.strip())
        except Exception:
            cloud_keys[p] = False
    return cloud_keys


def _test_cloud_api_key(
    provider_name: str, api_key: str, model: str
) -> tuple[bool, str]:
    provider = (provider_name or "openai").strip().lower()
    chosen_model = (model or "").strip()

    defaults = {
        "openai": "gpt-4o-mini",
        "google": "gemini-2.5-flash",
        "upstage": "solar-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "openrouter": "openai/gpt-4o-mini",
    }
    selected_model = chosen_model or defaults.get(provider, "gpt-4o-mini")

    try:
        if provider == "google":
            model_id = selected_model
            if not model_id.startswith("models/"):
                model_id = f"models/{model_id}"
            url = f"https://generativelanguage.googleapis.com/v1beta/{model_id}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8},
            }
            r = requests.post(url, json=payload, timeout=25)
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Google API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Google API 오류 {r.status_code}"

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": selected_model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            }
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Anthropic API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Anthropic API 오류 {r.status_code}"

        base_urls = {
            "openai": "https://api.openai.com/v1",
            "upstage": "https://api.upstage.ai/v1/solar",
            "openrouter": "https://openrouter.ai/api/v1",
        }
        if provider not in base_urls:
            return False, "실패: 지원하지 않는 클라우드 제공자입니다."

        url = f"{base_urls[provider]}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["X-Title"] = "WebmailSummary"
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 8,
        }
        if provider == "upstage":
            upstage_urls = [
                "https://api.upstage.ai/v1/solar/chat/completions",
                "https://api.upstage.ai/v1/chat/completions",
            ]
            model_candidates = [selected_model]
            for m in ["solar-mini", "solar-pro"]:
                if m not in model_candidates:
                    model_candidates.append(m)

            last_code = 0
            for test_url in upstage_urls:
                for test_model in model_candidates:
                    test_payload = {
                        "model": test_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "temperature": 0,
                        "max_tokens": 8,
                    }
                    r = requests.post(
                        test_url, headers=headers, json=test_payload, timeout=25
                    )
                    last_code = r.status_code
                    if r.status_code == 200:
                        return (
                            True,
                            f"성공: UPSTAGE API 키가 유효합니다. (모델: {test_model})",
                        )
                    if r.status_code in {401, 403}:
                        return False, "실패: Upstage API 키 인증에 실패했습니다."
            return False, f"실패: Upstage API 오류 {last_code}"

        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code == 200:
            return (
                True,
                f"성공: {provider.upper()} API 키가 유효합니다. (모델: {selected_model})",
            )
        if r.status_code in {401, 403}:
            return False, f"실패: {provider.upper()} API 키 인증에 실패했습니다."
        return False, f"실패: {provider.upper()} API 오류 {r.status_code}"
    except Exception as e:
        return False, f"실패: API 테스트 중 예외가 발생했습니다. ({str(e)[:120]})"


def _pick_directory_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select Folder")
        root.destroy()
        return str(path) if path else None
    except Exception:
        return None


def _is_ai_ready(settings: Settings) -> bool:
    backend = (settings.llm_backend or "local").strip().lower()
    if backend == "local":
        ready = check_local_ready(model_id=settings.local_model_id)
        return ready.engine_ok and ready.model_ok
    if backend in {"openrouter", "cloud"}:
        provider_name = (settings.cloud_provider or "openai").strip().lower()
        keys = _get_cloud_keys()
        return keys.get(provider_name, False)
    return False


def _is_setup_complete(settings: Settings) -> bool:
    # Essential: IMAP host/user and AI ready
    if not settings.imap_host or not settings.imap_user:
        return False
    return _is_ai_ready(settings)


def _normalize_version(value: str) -> str:
    v = str(value or "").strip()
    if v.lower().startswith("v"):
        v = v[1:]
    return v


def _get_repo_declared_version() -> str | None:
    try:
        repo_root = Path(__file__).resolve().parents[3]
        pyproject = repo_root / "pyproject.toml"
        if not pyproject.exists():
            return None
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if not m:
            return None
        v = _normalize_version(m.group(1))
        return v or None
    except Exception:
        return None


def _get_app_version() -> str:
    # In local src runs, prefer repo-declared version to avoid stale global
    # dist-info metadata overshadowing the working copy version.
    local_declared = _get_repo_declared_version()
    if local_declared:
        return local_declared
    try:
        return _normalize_version(importlib_metadata.version("webmail-summary"))
    except Exception:
        return "0.0.0"


def _parse_iso_datetime(value: str) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _build_update_state(settings: Settings) -> dict:
    now = datetime.now(timezone.utc)
    current = _get_app_version()
    latest = _normalize_version(settings.update_latest_version)

    has_update = False
    if latest:
        try:
            has_update = Version(latest) > Version(current)
        except InvalidVersion:
            has_update = latest != current

    snooze_until = _parse_iso_datetime(settings.update_snooze_until)
    is_snoozed = bool(snooze_until and snooze_until > now)
    is_skipped = bool(
        settings.update_skip_version and settings.update_skip_version == latest
    )

    return {
        "current": current,
        "latest": latest,
        "repo": _effective_update_repo(settings),
        "channel": settings.update_channel,
        "auto_check_enabled": bool(settings.update_auto_check_enabled),
        "last_checked_at": settings.update_last_checked_at,
        "last_check_status": settings.update_last_check_status,
        "download_url": settings.update_download_url,
        "release_page_url": _github_release_url(settings),
        "snooze_until": settings.update_snooze_until,
        "has_update": has_update,
        "is_snoozed": is_snoozed,
        "is_skipped": is_skipped,
        "show_notice": bool(has_update and not is_snoozed and not is_skipped),
    }


_UPDATE_AUTO_CHECK_INTERVAL_HOURS = 6
_DEFAULT_UPDATE_REPO = "repairer5812/ai-email-summarizer"


def _effective_update_repo(settings: Settings) -> str:
    repo = str(settings.update_repo or "").strip()
    return repo or _DEFAULT_UPDATE_REPO


def _parse_github_repo(value: str) -> tuple[str, str] | None:
    repo = str(value or "").strip()
    if not repo:
        return None
    if repo.startswith("https://github.com/"):
        repo = repo.replace("https://github.com/", "", 1)
    repo = repo.strip("/")
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _github_release_url(settings: Settings) -> str | None:
    parsed = _parse_github_repo(_effective_update_repo(settings))
    if not parsed:
        return None
    owner, repo = parsed
    return f"https://github.com/{owner}/{repo}/releases/latest"


def _check_github_release(conn, settings: Settings, *, force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    now_epoch = int(now.timestamp())

    parsed = _parse_github_repo(_effective_update_repo(settings))
    if not parsed:
        if force:
            _set_setting(conn, "update_last_check_status", "repo_not_set")
            _set_setting(conn, "update_last_checked_at", now_iso)
            conn.commit()
        return {"ok": False, "reason": "repo_not_set"}

    if not force and not settings.update_auto_check_enabled:
        return {"ok": False, "reason": "auto_check_disabled"}

    if not force:
        last = _parse_iso_datetime(settings.update_last_checked_at)
        if last is not None:
            delta_h = (now - last).total_seconds() / 3600.0
            if delta_h < float(_UPDATE_AUTO_CHECK_INTERVAL_HOURS):
                return {"ok": False, "reason": "not_due"}

    try:
        lock_until = int(
            (_get_setting(conn, "update_check_lock_until") or "0").strip() or "0"
        )
    except Exception:
        lock_until = 0
    if lock_until > now_epoch:
        return {"ok": False, "reason": "locked"}

    _set_setting(conn, "update_check_lock_until", str(now_epoch + 60))
    conn.commit()

    owner, repo = parsed
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"webmail-summary/{_get_app_version()}",
    }
    etag = (_get_setting(conn, "update_check_etag") or "").strip()
    if etag:
        headers["If-None-Match"] = etag

    try:
        if settings.update_channel == "stable":
            url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
            r = requests.get(url, headers=headers, timeout=(3.05, 10))
            if r.status_code == 304:
                _set_setting(conn, "update_last_checked_at", now_iso)
                _set_setting(conn, "update_last_check_status", "not_modified")
                conn.commit()
                return {"ok": True, "reason": "not_modified"}
            if r.status_code != 200:
                _set_setting(conn, "update_last_checked_at", now_iso)
                _set_setting(conn, "update_last_check_status", f"http_{r.status_code}")
                conn.commit()
                return {"ok": False, "reason": f"http_{r.status_code}"}
            release = r.json() or {}
        else:
            url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=20"
            r = requests.get(url, headers=headers, timeout=(3.05, 10))
            if r.status_code == 304:
                _set_setting(conn, "update_last_checked_at", now_iso)
                _set_setting(conn, "update_last_check_status", "not_modified")
                conn.commit()
                return {"ok": True, "reason": "not_modified"}
            if r.status_code != 200:
                _set_setting(conn, "update_last_checked_at", now_iso)
                _set_setting(conn, "update_last_check_status", f"http_{r.status_code}")
                conn.commit()
                return {"ok": False, "reason": f"http_{r.status_code}"}
            items = r.json() or []
            release = {}
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if bool(it.get("draft")):
                        continue
                    release = it
                    break

        new_etag = str(r.headers.get("ETag") or "").strip()
        if new_etag:
            _set_setting(conn, "update_check_etag", new_etag)

        tag = _normalize_version(
            str(release.get("tag_name") or release.get("name") or "")
        )
        html_url = str(release.get("html_url") or "").strip()
        download_url = html_url
        assets = release.get("assets")
        if isinstance(assets, list) and assets:
            first = assets[0]
            if isinstance(first, dict):
                dl = str(first.get("browser_download_url") or "").strip()
                if dl:
                    download_url = dl

        _set_setting(conn, "update_latest_version", tag)
        _set_setting(conn, "update_download_url", download_url)
        _set_setting(conn, "update_last_checked_at", now_iso)
        _set_setting(conn, "update_last_check_status", "ok")
        conn.commit()
        return {"ok": True, "reason": "ok"}
    except Exception:
        _set_setting(conn, "update_last_checked_at", now_iso)
        _set_setting(conn, "update_last_check_status", "network_error")
        conn.commit()
        return {"ok": False, "reason": "network_error"}
    finally:
        _set_setting(conn, "update_check_lock_until", "0")
        conn.commit()


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        settings = load_settings(conn)
        configured = _get_setting(conn, "imap_host") is not None
        active_jobs = _get_active_jobs(conn)

        if not configured:
            return RedirectResponse("/setup", status_code=302)

        # AI readiness
        ai_ready = _is_ai_ready(settings)
        setup_complete = _is_setup_complete(settings)
        local_ready = check_local_ready(model_id=settings.local_model_id)

        provider_name = (settings.cloud_provider or "openai").strip().lower()
        cloud_keys = _get_cloud_keys()

        _check_github_release(conn, settings, force=False)
        settings = load_settings(conn)
        update_state = _build_update_state(settings)

        # Day counts
        rows_days = list(
            conn.execute(
                "SELECT substr(internal_date, 1, 10) AS day, COUNT(*) "
                "FROM messages "
                "WHERE internal_date IS NOT NULL AND length(internal_date) >= 10 "
                "GROUP BY day ORDER BY day DESC LIMIT 90"
            ).fetchall()
        )
        from webmail_summary.index.mail_repo import get_daily_overview

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

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "theme": settings.ui_theme,
            "days": day_cards,
            "flash": {"saved": saved},
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
            },
        },
    )


@router.get("/api/ui/days")
def api_get_days():
    from webmail_summary.index.db import get_conn
    from webmail_summary.index.mail_repo import get_daily_overview

    conn = get_conn(_db_path())
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


@router.get("/day/{date_key}", response_class=HTMLResponse)
def day_view(request: Request, date_key: str):
    dk = (date_key or "").strip()
    if len(dk) != 10 or dk[4] != "-" or dk[7] != "-":
        return RedirectResponse("/", status_code=302)

    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        settings = load_settings(conn)
        rows = list_messages_by_date(conn, date_prefix=dk)
        active_jobs = _get_active_jobs(conn)
        setup_complete = _is_setup_complete(settings)

        # Determine if there's an active resummarize job for THIS date
        active_resum = None
        if active_jobs.get("resummarize"):
            job = active_jobs["resummarize"]
            if job.get("date_key") == dk:
                active_resum = job

    finally:
        conn.close()

    items: list[dict] = []

    for r in rows:
        internal = str(r[3] or "")
        try:
            tags = json.loads(str(r[5] or "[]"))
        except Exception:
            tags = []
        try:
            topics = json.loads(str(r[6] or "[]"))
        except Exception:
            topics = []
        items.append(
            {
                "id": int(r[0]),
                "subject": str(r[1] or ""),
                "time": time_kst(internal, with_seconds=False),
                "time_full": format_kst(internal, with_seconds=True),
                "summary": coerce_summary_text(str(r[4] or "")),
                "tags": tags if isinstance(tags, list) else [],
                "topics": topics if isinstance(topics, list) else [],
                "has_rendered": bool(r[8]),
                "summarize_ms": _fmt_summarize_ms(r[10] if len(r) > 10 else None),
            }
        )

    return templates.TemplateResponse(
        "day.html",
        {
            "request": request,
            "theme": settings.ui_theme,
            "day": dk,
            "items": items,
            "active": active_jobs,
            "active_resum": active_resum,
            "setup_complete": setup_complete,
        },
    )


@router.get("/message/{message_id}", response_class=HTMLResponse)
def message_detail(request: Request, message_id: int):
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        settings = load_settings(conn)
        row = get_message_detail(conn, int(message_id))
        active_jobs = _get_active_jobs(conn)
    finally:
        conn.close()
    if row is None:
        return RedirectResponse("/", status_code=302)

    subject = str(row[1] or "")
    internal_date = str(row[4] or "")
    summary = coerce_summary_text(str(row[5] or ""))
    tags_json = str(row[6] or "[]")
    topics_json = str(row[7] or "[]")
    rendered_html_path = row[9]
    summarized_at = str(row[10] or "") if len(row) > 10 else ""
    summarize_ms = row[11] if len(row) > 11 else None

    return_to = str(request.query_params.get("return_to") or "").strip()
    if len(return_to) == 10 and return_to[4] == "-" and return_to[7] == "-":
        back_href = f"/day/{return_to}"
    elif (
        len(internal_date) >= 10 and internal_date[4] == "-" and internal_date[7] == "-"
    ):
        back_href = f"/day/{internal_date[:10]}"
    else:
        back_href = "/"

    try:
        tags = json.loads(tags_json)
    except Exception:
        tags = []
    try:
        topics = json.loads(topics_json)
    except Exception:
        topics = []

    return templates.TemplateResponse(
        "message_detail.html",
        {
            "request": request,
            "theme": settings.ui_theme,
            "msg": {
                "id": int(row[0]),
                "subject": subject,
                "internal_date": format_kst(internal_date, with_seconds=True),
                "summary": summary,
                "tags": tags,
                "topics": topics,
                "has_rendered": bool(rendered_html_path),
                "summarized_at": format_kst(summarized_at, with_seconds=True)
                if summarized_at
                else "",
                "summarize_ms": _fmt_summarize_ms(summarize_ms),
                "back_href": back_href,
            },
            "active": active_jobs,
        },
    )


@router.get("/m/{message_id}/{path:path}")
def serve_message_file(message_id: int, path: str):
    from fastapi.responses import FileResponse

    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        row = conn.execute(
            "SELECT rendered_html_path FROM messages WHERE id = ?",
            (int(message_id),),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return RedirectResponse("/", status_code=302)

    rendered_path = str(row[0] or "")
    base_dir = Path(rendered_path).parent
    target = (base_dir / path).resolve()
    if base_dir.resolve() not in target.parents and target != base_dir.resolve():
        return RedirectResponse("/", status_code=302)
    if not target.exists() or not target.is_file():
        return RedirectResponse("/message/%d" % int(message_id), status_code=302)

    return FileResponse(str(target))


@router.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request):
    from webmail_summary.index.db import get_conn

    tab = str(request.query_params.get("tab") or "profile")

    conn = get_conn(_db_path())
    try:
        settings = load_settings(conn)
        active_jobs = _get_active_jobs(conn)

        provider_name = (settings.cloud_provider or "openai").strip().lower()
        cloud_keys = _get_cloud_keys()

        local_ready = check_local_ready(model_id=settings.local_model_id)
        if settings.imap_host and settings.imap_user:
            try:
                svc = f"webmail-summary::{settings.imap_host}"
                val = keyring.get_password(svc, settings.imap_user)
                imap_pass_set = bool(val and val.strip())
            except Exception:
                pass

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
                "sender_filter": settings.sender_filter or "hslee@tekville.com",
                "obsidian_root": settings.obsidian_root or "",
                "llm_backend": settings.llm_backend,
                "cloud_provider": provider_name,
                "local_model_id": settings.local_model_id,
                "openrouter_model": settings.openrouter_model,
                "external_max_bytes": str(settings.external_max_bytes),
                "revert_seen": settings.revert_seen_after_sync,
                "user_roles": settings.user_roles,
                "user_interests": settings.user_interests,
                "ui_theme": settings.ui_theme,
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
    return templates.TemplateResponse("setup.html", ctx)


@router.post("/setup/test-imap", response_class=HTMLResponse)
def setup_test_imap(
    request: Request,
    imap_host: str = Form(...),
    imap_port: int = Form(...),
    imap_user: str = Form(...),
    imap_password: str = Form(...),
):
    from webmail_summary.index.db import get_conn

    folders: list[str] = []
    status = "ok"
    error = None
    try:
        with ImapSession(imap_host, int(imap_port), imap_user, imap_password) as imap:
            folders = imap.list_folders()
    except Exception as e:
        status = "error"
        error = str(e)

    conn = get_conn(_db_path())
    try:
        _set_setting(conn, "imap_host", imap_host)
        _set_setting(conn, "imap_port", str(imap_port))
        _set_setting(conn, "imap_user", imap_user)
        conn.commit()
    finally:
        conn.close()

    service = f"webmail-summary::{imap_host}"

    keyring.set_password(service, imap_user, imap_password)

    conn2 = get_conn(_db_path())
    try:
        settings = load_settings(conn2)
        active_jobs = _get_active_jobs(conn2)
        provider_name = (settings.cloud_provider or "openai").strip().lower()
        cloud_keys = _get_cloud_keys()
        local_ready = check_local_ready(model_id=settings.local_model_id)
        ctx = {
            "request": request,
            "theme": settings.ui_theme,
            "active": active_jobs,
            "current_tab": "connection",
            "imap_pass_set": True,
            "defaults": {
                "imap_host": imap_host,
                "imap_port": str(imap_port),
                "imap_user": imap_user,
                "imap_folder": _get_setting(conn2, "imap_folder") or "INBOX",
                "sender_filter": _get_setting(conn2, "sender_filter")
                or "hslee@tekville.com",
                "obsidian_root": _get_setting(conn2, "obsidian_root")
                or str(default_obsidian_root()),
                "llm_backend": settings.llm_backend,
                "cloud_provider": provider_name,
                "local_model_id": settings.local_model_id,
                "openrouter_model": settings.openrouter_model,
                "external_max_bytes": _get_setting(conn2, "external_max_bytes")
                or str(1024**3),
                "revert_seen_after_sync": _get_setting(conn2, "revert_seen_after_sync")
                or "0",
                "user_roles": settings.user_roles,
                "user_interests": settings.user_interests,
                "ui_theme": settings.ui_theme,
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
            "folders": folders,
            "status": {"status": status, "error": error},
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
        conn2.close()

    return templates.TemplateResponse("setup.html", ctx)


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

    ok, msg = _test_cloud_api_key(provider, candidate, model)
    return JSONResponse({"ok": ok, "message": msg})


@router.post("/setup/save", response_class=HTMLResponse)
def setup_save(
    imap_host: str = Form(""),
    imap_port: str = Form("993"),
    imap_user: str = Form(""),
    imap_folder: str = Form("INBOX"),
    sender_filter: str = Form("hslee@tekville.com"),
    obsidian_root: str = Form(""),
    llm_backend: str = Form("local"),
    local_model_id: str = Form("standard"),
    cloud_provider: str = Form("openai"),
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
    ui_theme: str = Form("trust"),
    current_tab: str = Form("profile"),
):
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        # Save whatever fields are present in the form submit
        if imap_host:
            _set_setting(conn, "imap_host", imap_host)
        if imap_port:
            _set_setting(conn, "imap_port", imap_port)
        if imap_user:
            _set_setting(conn, "imap_user", imap_user)
        if imap_folder:
            _set_setting(conn, "imap_folder", imap_folder)
        if sender_filter:
            _set_setting(conn, "sender_filter", sender_filter)
        if obsidian_root:
            _set_setting(conn, "obsidian_root", obsidian_root)
        if llm_backend:
            _set_setting(conn, "llm_backend", llm_backend.strip().lower())
        if cloud_provider:
            _set_setting(conn, "cloud_provider", cloud_provider.strip().lower())
        if local_model_id:
            _set_setting(
                conn,
                "local_model_id",
                get_local_model(local_model_id.strip().lower()).id,
            )
        if openrouter_model:
            _set_setting(conn, "openrouter_model", openrouter_model.strip())
        if external_max_bytes:
            _set_setting(conn, "external_max_bytes", external_max_bytes.strip())
        if ui_theme:
            _set_setting(conn, "ui_theme", ui_theme)

        if user_roles:
            _set_setting(conn, "user_roles", json.dumps(user_roles))
        _set_setting(conn, "user_interests", user_interests)

        upd_ch = (update_channel or "stable").strip().lower()
        if upd_ch not in {"stable", "beta"}:
            upd_ch = "stable"
        _set_setting(conn, "update_channel", upd_ch)
        _set_setting(
            conn, "update_latest_version", (update_latest_version or "").strip()
        )
        _set_setting(conn, "update_repo", _DEFAULT_UPDATE_REPO)
        _set_setting(
            conn,
            "update_auto_check_enabled",
            "1"
            if (update_auto_check_enabled or "").strip().lower()
            in {"1", "on", "true", "yes"}
            else "0",
        )
        _set_setting(conn, "update_snooze_until", (update_snooze_until or "").strip())
        _set_setting(conn, "update_skip_version", (update_skip_version or "").strip())
        _set_setting(
            conn, "update_last_checked_at", (update_last_checked_at or "").strip()
        )
        _set_setting(conn, "update_download_url", (update_download_url or "").strip())

        rev = (revert_seen_after_sync or "").strip().lower()
        _set_setting(
            conn,
            "revert_seen_after_sync",
            "1" if rev in {"1", "on", "true", "yes"} else "0",
        )

        _set_setting(conn, "configured_at", datetime.now(timezone.utc).isoformat())
        conn.commit()
    finally:
        conn.close()

    # Store API keys in Keyring
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

    # Wizard logic: redirect to next tab or finish
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
    picked = _pick_directory_dialog()
    if not picked:
        return RedirectResponse("/setup", status_code=302)
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        _set_setting(conn, "obsidian_root", picked)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/setup", status_code=302)


@router.post("/setup/save-partial")
def setup_save_partial(
    ui_theme: str = Form(None),
    llm_backend: str = Form(None),
):
    """Save individual settings without full redirect."""
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        if ui_theme:
            _set_setting(conn, "ui_theme", ui_theme)
        if llm_backend:
            _set_setting(conn, "llm_backend", llm_backend.strip().lower())
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/updates/snooze-week")
def updates_snooze_week():
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        _set_setting(conn, "update_snooze_until", until)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.post("/updates/skip-latest")
def updates_skip_latest():
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        latest = (_get_setting(conn, "update_latest_version") or "").strip()
        _set_setting(conn, "update_skip_version", latest)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.post("/updates/check-now")
def updates_check_now():
    from webmail_summary.index.db import get_conn

    conn = get_conn(_db_path())
    try:
        settings = load_settings(conn)
        _check_github_release(conn, settings, force=True)
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)
