from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webmail_summary.index.mail_repo import get_message_detail, list_messages_by_date
from webmail_summary.index.settings import load_settings
from webmail_summary.jobs.tasks_resummarize import _needs_resummarize
from webmail_summary.ui.settings_gateway import db_path
from webmail_summary.ui.timefmt import format_kst, time_kst
from webmail_summary.ui.web_shared import fmt_summarize_ms, get_active_jobs, templates
from webmail_summary.util.jsonish import coerce_summary_text

router = APIRouter()


@router.get("/day/{date_key}", response_class=HTMLResponse)
def day_view(request: Request, date_key: str):
    from webmail_summary.index.db import get_conn

    dk = (date_key or "").strip()
    if len(dk) != 10 or dk[4] != "-" or dk[7] != "-":
        return RedirectResponse("/", status_code=302)

    conn = get_conn(db_path())
    try:
        settings = load_settings(conn)
        rows = list_messages_by_date(conn, date_prefix=dk)
        active_jobs = get_active_jobs(conn)
        setup_complete = bool(settings.imap_host and settings.imap_user)

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
                "summarize_ms": fmt_summarize_ms(r[10] if len(r) > 10 else None),
                "needs_resummarize": _needs_resummarize(
                    coerce_summary_text(str(r[4] or ""))
                ),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="day.html",
        context={
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

    conn = get_conn(db_path())
    try:
        settings = load_settings(conn)
        row = get_message_detail(conn, int(message_id))
        active_jobs = get_active_jobs(conn)
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
    return_day = ""
    if len(return_to) == 10 and return_to[4] == "-" and return_to[7] == "-":
        return_day = return_to
        back_href = f"/day/{return_to}"
    elif (
        len(internal_date) >= 10 and internal_date[4] == "-" and internal_date[7] == "-"
    ):
        return_day = internal_date[:10]
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
        request=request,
        name="message_detail.html",
        context={
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
                "summarize_ms": fmt_summarize_ms(summarize_ms),
                "back_href": back_href,
                "return_day": return_day,
            },
            "active": active_jobs,
        },
    )


@router.get("/message/{message_id}/original", response_class=HTMLResponse)
def message_original(request: Request, message_id: int):
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        settings = load_settings(conn)
        row = get_message_detail(conn, int(message_id))
        active_jobs = get_active_jobs(conn)
    finally:
        conn.close()
    if row is None:
        return RedirectResponse("/", status_code=302)

    subject = str(row[1] or "")
    internal_date = str(row[4] or "")
    rendered_html_path = row[9]
    if not rendered_html_path:
        return RedirectResponse(f"/message/{int(message_id)}", status_code=302)

    return_to = str(request.query_params.get("return_to") or "").strip()
    if len(return_to) == 10 and return_to[4] == "-" and return_to[7] == "-":
        back_href = f"/day/{return_to}"
    elif (
        len(internal_date) >= 10 and internal_date[4] == "-" and internal_date[7] == "-"
    ):
        back_href = f"/day/{internal_date[:10]}"
    else:
        back_href = "/"

    return templates.TemplateResponse(
        request=request,
        name="message_original.html",
        context={
            "request": request,
            "theme": settings.ui_theme,
            "msg": {
                "id": int(row[0]),
                "subject": subject,
                "internal_date": format_kst(internal_date, with_seconds=True),
                "back_href": back_href,
            },
            "active": active_jobs,
        },
    )


@router.get("/m/{message_id}/{path:path}")
def serve_message_file(request: Request, message_id: int, path: str):
    from fastapi.responses import FileResponse
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        row = conn.execute(
            "SELECT rendered_html_path FROM messages WHERE id = ?", (int(message_id),)
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

    normalized_path = str(path or "").strip().lower()
    embed = str(request.query_params.get("embed") or "").strip()
    if normalized_path == "rendered.html" and embed != "1":
        return_to = str(request.query_params.get("return_to") or "").strip()
        if len(return_to) == 10 and return_to[4] == "-" and return_to[7] == "-":
            return RedirectResponse(
                f"/message/{int(message_id)}/original?return_to={return_to}",
                status_code=302,
            )
        return RedirectResponse(f"/message/{int(message_id)}/original", status_code=302)

    return FileResponse(str(target))
