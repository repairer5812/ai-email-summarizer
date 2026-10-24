from __future__ import annotations

from webmail_summary.ui.routes import router


def _route_paths(routes, prefix: str = "") -> set[str]:
    # FastAPI >= 0.16x keeps included routers as _IncludedRouter entries
    # (no .path); older versions copy the child routes. Walk both shapes.
    out: set[str] = set()
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(route, "include_context", None)
            sub_prefix = prefix + str(getattr(ctx, "prefix", "") or "")
            out |= _route_paths(inner.routes, sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            out.add(prefix + path)
    return out


def test_ui_router_includes_expected_paths():
    paths = _route_paths(router.routes)

    assert "/" in paths
    assert "/setup" in paths
    assert "/setup/save" in paths
    assert "/day/{date_key}" in paths
    assert "/message/{message_id}" in paths
    assert "/updates/check-now" in paths
    assert "/lifecycle/request-exit" in paths
