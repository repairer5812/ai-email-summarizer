from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi.templating import Jinja2Templates

from webmail_summary.ui.i18n import t as _t
from webmail_summary.ui.i18n import ui_lang as _ui_lang
from webmail_summary.ui.updates import _get_app_version


templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.globals["t"] = _t
templates.env.globals["ui_lang"] = _ui_lang


def fmt_summarize_ms(ms: int | None) -> str:
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


def static_asset_version(asset_name: str) -> str:
    try:
        name = str(asset_name or "").strip().lstrip("/")
        if not name:
            return _get_app_version()
        static_dir = Path(__file__).resolve().parent / "static"
        p = (static_dir / name).resolve()
        if static_dir not in p.parents and p != static_dir:
            return _get_app_version()
        if not p.exists() or not p.is_file():
            return _get_app_version()
        data = p.read_bytes()
        h = hashlib.sha1(data).hexdigest()[:10]
        return f"{_get_app_version()}-{h}"
    except Exception:
        return _get_app_version()


def get_active_jobs(conn) -> dict:
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


try:
    templates.env.globals["app_version"] = _get_app_version
    templates.env.globals["asset_v"] = static_asset_version
except Exception:
    pass
