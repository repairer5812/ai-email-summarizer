from __future__ import annotations


from webmail_summary.ui import routes


def test_static_asset_version_uses_content_hash_for_known_assets():
    css_v = routes._static_asset_version("app.css")
    js_v = routes._static_asset_version("app.js")

    assert "-" in css_v
    assert "-" in js_v
    assert len(css_v.rsplit("-", 1)[-1]) == 10
    assert len(js_v.rsplit("-", 1)[-1]) == 10


def test_static_asset_version_falls_back_for_missing_asset():
    v = routes._static_asset_version("does-not-exist.css")
    assert v == routes._get_app_version()
