from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from webmail_summary.index.db import get_conn
from webmail_summary.index.settings import load_settings


def _mk_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from webmail_summary.app.main import create_app

    return create_app()


def _load_saved_settings(tmp_path):
    conn = get_conn(tmp_path / "WebmailSummary" / "db.sqlite3")
    try:
        return load_settings(conn)
    finally:
        conn.close()


def test_setup_save_partial_persists_ai_selection_and_returns_local_ready(
    tmp_path, monkeypatch
):
    app = _mk_app(tmp_path, monkeypatch)
    from webmail_summary.ui import routes_setup

    monkeypatch.setattr(
        routes_setup,
        "check_local_ready",
        lambda model_id: SimpleNamespace(
            engine_ok=(model_id == "fast"),
            model_ok=False,
            engine_path="C:/llama/llama-cli.exe",
            model_path=None,
        ),
    )

    client = TestClient(app)
    r = client.post(
        "/setup/save-partial",
        data={
            "llm_backend": "local",
            "cloud_provider": "OpenRouter",
            "cloud_multimodal_enabled": "1",
            "local_model_id": "exaone35_2.4b",
            "local_engine": "invalid",
            "openrouter_model": "google/gemini-2.5-flash",
        },
    )

    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["saved"]["llm_backend"] == "local"
    assert j["saved"]["cloud_provider"] == "openrouter"
    assert j["saved"]["cloud_multimodal_enabled"] is True
    assert j["saved"]["local_model_id"] == "fast"
    assert j["saved"]["local_engine"] == "auto"
    assert j["saved"]["openrouter_model"] == "google/gemini-2.5-flash"
    assert j["saved"]["local_ready"]["engine_ok"] is True
    assert j["saved"]["local_ready"]["model_ok"] is False

    settings = _load_saved_settings(tmp_path)
    assert settings.llm_backend == "local"
    assert settings.cloud_provider == "openrouter"
    assert settings.cloud_multimodal_enabled is True
    assert settings.local_model_id == "fast"
    assert settings.local_engine == "auto"
    assert settings.openrouter_model == "google/gemini-2.5-flash"
