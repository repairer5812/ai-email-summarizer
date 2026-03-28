from __future__ import annotations

from fastapi import APIRouter

from webmail_summary.ui.updates import _schedule_app_shutdown
from webmail_summary.util.ui_lifecycle import mark_ui_heartbeat, mark_ui_tab_closed

router = APIRouter()


@router.post("/lifecycle/heartbeat")
def lifecycle_heartbeat():
    try:
        mark_ui_heartbeat()
    except Exception:
        pass
    return {"ok": True}


@router.post("/lifecycle/tab-closed")
def lifecycle_tab_closed():
    try:
        mark_ui_tab_closed()
    except Exception:
        pass
    return {"ok": True}


@router.post("/lifecycle/request-exit")
def lifecycle_request_exit():
    try:
        mark_ui_tab_closed()
    except Exception:
        pass
    _schedule_app_shutdown(delay_s=0.2)
    return {"ok": True}
