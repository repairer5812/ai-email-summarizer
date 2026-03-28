from __future__ import annotations

from webmail_summary.ui.routes import router


def test_ui_router_includes_expected_paths():
    paths = {route.path for route in router.routes}

    assert "/" in paths
    assert "/setup" in paths
    assert "/setup/save" in paths
    assert "/day/{date_key}" in paths
    assert "/message/{message_id}" in paths
    assert "/updates/check-now" in paths
    assert "/lifecycle/request-exit" in paths
