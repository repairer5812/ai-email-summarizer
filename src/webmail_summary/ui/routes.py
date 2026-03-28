from __future__ import annotations

from fastapi import APIRouter

from webmail_summary.ui.routes_home import router as home_router
from webmail_summary.ui.routes_lifecycle import router as lifecycle_router
from webmail_summary.ui.routes_messages import router as message_router
from webmail_summary.ui.routes_setup import router as setup_router
from webmail_summary.ui.updates import _get_app_version as _routes_get_app_version
from webmail_summary.ui.updates import router as updates_router
from webmail_summary.ui.web_shared import (
    static_asset_version as _routes_static_asset_version,
)

_get_app_version = _routes_get_app_version
_static_asset_version = _routes_static_asset_version

router = APIRouter()
router.include_router(home_router)
router.include_router(message_router)
router.include_router(setup_router)
router.include_router(lifecycle_router)
router.include_router(updates_router)
