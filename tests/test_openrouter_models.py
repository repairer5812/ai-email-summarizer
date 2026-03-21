from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@dataclass
class _Resp:
    status_code: int
    payload: dict
    text: str = ""

    def json(self) -> dict:
        return self.payload


def _mk_app(tmp_path: Path):
    os.environ["LOCALAPPDATA"] = str(tmp_path)
    from webmail_summary.app.main import create_app

    return create_app()


def test_openrouter_models_requires_key_or_cache(tmp_path: Path, monkeypatch):
    app = _mk_app(tmp_path)
    from webmail_summary.api import routes_openrouter

    monkeypatch.setattr(routes_openrouter.keyring, "get_password", lambda *a, **k: "")
    monkeypatch.setattr(routes_openrouter.requests, "get", lambda *a, **k: None)

    c = TestClient(app)
    r = c.get("/api/openrouter/models")
    assert r.status_code == 409
    j = r.json()
    assert j.get("error") == "openrouter_models_unavailable"


def test_openrouter_models_uses_cache_file_without_key(tmp_path: Path, monkeypatch):
    app = _mk_app(tmp_path)
    from webmail_summary.api import routes_openrouter

    monkeypatch.setattr(routes_openrouter.keyring, "get_password", lambda *a, **k: "")
    # Write cache file
    cache = tmp_path / "WebmailSummary" / "runtime" / "openrouter_models_cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "updated_at": 0,
                "models": [
                    {
                        "id": "google/gemma-3-4b-it",
                        "name": "Gemma 3 4B",
                        "context_length": 8192,
                        "prompt_price": "0",
                        "completion_price": "0",
                        "is_free_variant": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    c = TestClient(app)
    r = c.get("/api/openrouter/models")
    assert r.status_code == 200
    j = r.json()
    assert j.get("count") == 1
    assert j["models"][0]["id"] == "google/gemma-3-4b-it"


def test_openrouter_models_fetches_and_filters(tmp_path: Path, monkeypatch):
    app = _mk_app(tmp_path)
    from webmail_summary.api import routes_openrouter

    monkeypatch.setattr(
        routes_openrouter.keyring, "get_password", lambda *a, **k: "sk-or-test"
    )

    def _fake_get(url, headers=None, timeout=0):
        assert url.endswith("/api/v1/models")
        assert headers and "Authorization" in headers
        return _Resp(
            status_code=200,
            payload={
                "data": [
                    {
                        "id": "google/gemma-3-4b-it",
                        "name": "Gemma 3 4B",
                        "context_length": 8192,
                        "pricing": {"prompt": "0.1", "completion": "0.2"},
                    },
                    {
                        "id": "meta-llama/llama-3.1-8b-instruct:free",
                        "name": "Llama 3.1 8B (free)",
                        "context_length": 8192,
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            },
        )

    monkeypatch.setattr(routes_openrouter.requests, "get", _fake_get)
    c = TestClient(app)

    r1 = c.get("/api/openrouter/models")
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1.get("count") == 2

    r2 = c.get("/api/openrouter/models?q=llama")
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2.get("count") == 1
    assert "llama" in j2["models"][0]["id"]
