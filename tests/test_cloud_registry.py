from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import webmail_summary.llm.openrouter as openrouter
import webmail_summary.llm.provider as provider_mod
import webmail_summary.ui.setup_service as setup_service
from webmail_summary.llm import cloud_registry
from webmail_summary.llm.openrouter import CloudConfig, CloudProvider
from webmail_summary.llm.provider import LlmNotReady, get_llm_provider

SECRET = "test-key-123"


@dataclass
class _Resp:
    status_code: int
    payload: dict
    text: str = ""
    headers: dict | None = None

    def json(self) -> dict:
        return self.payload


def _cloud_settings(provider: str, model: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        llm_backend="cloud", cloud_provider=provider, openrouter_model=model
    )


# The values below are the ones provider.py and setup_service.py hard-coded
# before the registry existed. They must not move.
EXPECTED = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-3-5-haiku-20241022"),
    "google": ("https://generativelanguage.googleapis.com", "gemini-2.5-flash"),
    "upstage": ("https://api.upstage.ai/v1/solar", "solar-mini"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
}


def test_registry_keeps_previous_table():
    assert cloud_registry.PROVIDER_IDS == (
        "openai",
        "anthropic",
        "google",
        "upstage",
        "openrouter",
    )
    for pid, (base_url, model) in EXPECTED.items():
        spec = cloud_registry.PROVIDERS[pid]
        assert (spec.base_url, spec.default_model) == (base_url, model)
    assert cloud_registry.keyring_service("google") == "webmail-summary::google"
    assert cloud_registry.resolve_provider("nope").id == "openai"
    assert cloud_registry.resolve_provider(None).id == "openai"
    assert cloud_registry.get_provider(" Google ").id == "google"


@pytest.mark.parametrize("pid", list(EXPECTED))
def test_get_llm_provider_builds_cloud_config_from_registry(monkeypatch, pid):
    seen: list[tuple[str, str]] = []

    def _get_password(service, user):
        seen.append((service, user))
        return SECRET

    monkeypatch.setattr(provider_mod.keyring, "get_password", _get_password)
    prov = get_llm_provider(_cloud_settings(pid))
    base_url, model = EXPECTED[pid]
    assert prov._cfg == CloudConfig(api_key=SECRET, model=model, base_url=base_url)
    assert seen == [(f"webmail-summary::{pid}", "api_key")]

    chosen = get_llm_provider(_cloud_settings(pid, model=" custom-model "))
    assert chosen._cfg.model == "custom-model"


def test_get_llm_provider_unknown_cloud_falls_back_to_openai(monkeypatch):
    monkeypatch.setattr(provider_mod.keyring, "get_password", lambda s, u: SECRET)
    prov = get_llm_provider(_cloud_settings("mystery"))
    assert prov._cfg.base_url == "https://api.openai.com/v1"
    assert prov._cfg.model == "gpt-4o-mini"


def test_get_llm_provider_without_key_is_not_ready(monkeypatch):
    monkeypatch.setattr(provider_mod.keyring, "get_password", lambda s, u: None)
    with pytest.raises(LlmNotReady, match="GOOGLE API key not set in setup"):
        get_llm_provider(_cloud_settings("google"))


def test_get_cloud_keys_checks_every_provider(monkeypatch):
    seen: list[str] = []

    def _get_password(service, user):
        seen.append(service)
        return " sk " if service.endswith("openrouter") else ""

    monkeypatch.setattr(setup_service.keyring, "get_password", _get_password)
    assert setup_service.get_cloud_keys() == {
        "openai": False,
        "anthropic": False,
        "google": False,
        "upstage": False,
        "openrouter": True,
    }
    assert seen == [f"webmail-summary::{p}" for p in cloud_registry.PROVIDER_IDS]


class _PostRecorder:
    def __init__(self, statuses):
        self.calls: list[dict] = []
        self._statuses = list(statuses)

    def __call__(self, url, headers=None, json=None, timeout=0):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        status = self._statuses.pop(0) if self._statuses else 200
        return _Resp(status_code=status, payload={})


def test_key_test_google_sends_key_in_header_not_url(monkeypatch):
    rec = _PostRecorder([200])
    monkeypatch.setattr(setup_service.requests, "post", rec)

    ok, msg = setup_service.test_cloud_api_key("google", SECRET, "")

    assert (ok, msg) == (True, "성공: Google API 키가 유효합니다. (모델: gemini-2.5-flash)")
    call = rec.calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert SECRET not in call["url"]
    assert call["headers"] == {"x-goog-api-key": SECRET}
    assert call["json"] == {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8},
    }
    assert call["timeout"] == 25


def test_key_test_anthropic_and_openai_compatible_requests(monkeypatch):
    rec = _PostRecorder([200, 401, 500])
    monkeypatch.setattr(setup_service.requests, "post", rec)

    assert setup_service.test_cloud_api_key("anthropic", SECRET, "") == (
        True,
        "성공: Anthropic API 키가 유효합니다. (모델: claude-3-5-haiku-20241022)",
    )
    assert setup_service.test_cloud_api_key("openrouter", SECRET, "x/y") == (
        False,
        "실패: OPENROUTER API 키 인증에 실패했습니다.",
    )
    assert setup_service.test_cloud_api_key("OpenAI", SECRET, "") == (
        False,
        "실패: OPENAI API 오류 500",
    )
    anthropic, openrouter_call, openai = rec.calls
    assert anthropic["url"] == "https://api.anthropic.com/v1/messages"
    assert anthropic["headers"] == {
        "x-api-key": SECRET,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    assert anthropic["json"] == {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "ping"}],
    }
    assert openrouter_call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert openrouter_call["headers"] == {
        "Authorization": f"Bearer {SECRET}",
        "Content-Type": "application/json",
        "X-Title": "WebmailSummary",
    }
    assert openrouter_call["json"]["model"] == "x/y"
    assert openai["url"] == "https://api.openai.com/v1/chat/completions"
    assert "X-Title" not in openai["headers"]
    assert openai["json"] == {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 8,
    }


def test_key_test_upstage_tries_both_endpoints_and_models(monkeypatch):
    rec = _PostRecorder([404, 404, 404, 404, 200])
    monkeypatch.setattr(setup_service.requests, "post", rec)

    ok, msg = setup_service.test_cloud_api_key("upstage", SECRET, "solar-x")

    assert (ok, msg) == (True, "성공: UPSTAGE API 키가 유효합니다. (모델: solar-mini)")
    assert [(c["url"], c["json"]["model"]) for c in rec.calls] == [
        ("https://api.upstage.ai/v1/solar/chat/completions", "solar-x"),
        ("https://api.upstage.ai/v1/solar/chat/completions", "solar-mini"),
        ("https://api.upstage.ai/v1/solar/chat/completions", "solar-pro"),
        ("https://api.upstage.ai/v1/chat/completions", "solar-x"),
        ("https://api.upstage.ai/v1/chat/completions", "solar-mini"),
    ]

    rec2 = _PostRecorder([403])
    monkeypatch.setattr(setup_service.requests, "post", rec2)
    assert setup_service.test_cloud_api_key("upstage", SECRET, "") == (
        False,
        "실패: Upstage API 키 인증에 실패했습니다.",
    )


def test_key_test_rejects_unknown_provider_and_network_errors(monkeypatch):
    def _boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(setup_service.requests, "post", _boom)
    assert setup_service.test_cloud_api_key("mystery", SECRET, "") == (
        False,
        "실패: 지원하지 않는 클라우드 제공자입니다.",
    )
    ok, msg = setup_service.test_cloud_api_key("openai", SECRET, "")
    assert ok is False and msg.startswith("실패: API 테스트 중 네트워크 오류")


_GOOD_JSON = '{"summary": ["요약"], "tags": ["t"], "backlinks": [], "personal": false}'


def _install_session_post(monkeypatch, payload):
    calls: list[dict] = []

    def _post(url, headers=None, json=None, timeout=0):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Resp(status_code=200, payload=payload, text="")

    monkeypatch.setattr(openrouter._SESSION, "post", _post)
    return calls


def test_cloud_provider_gemini_keeps_key_out_of_url(monkeypatch):
    calls = _install_session_post(
        monkeypatch,
        {"candidates": [{"content": {"parts": [{"text": _GOOD_JSON}]}}]},
    )
    prov = CloudProvider(
        CloudConfig(
            api_key=SECRET,
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com",
        )
    )

    res = prov.summarize(subject="제목", body="본문")

    assert res.tags == ["t"]
    call = calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert SECRET not in call["url"]
    assert call["headers"] == {"x-goog-api-key": SECRET}
    assert call["json"]["generationConfig"] == {
        "temperature": 0.2,
        "response_mime_type": "application/json",
    }
    assert call["timeout"] == 120


def test_cloud_provider_anthropic_and_openrouter_requests(monkeypatch):
    calls = _install_session_post(
        monkeypatch, {"content": [{"type": "text", "text": _GOOD_JSON}]}
    )
    CloudProvider(
        CloudConfig(
            api_key=SECRET,
            model="claude-3-5-haiku-20241022",
            base_url="https://api.anthropic.com/v1",
        )
    ).summarize(subject="s", body="b")
    assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert calls[0]["headers"] == {
        "x-api-key": SECRET,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    assert calls[0]["timeout"] == 60

    calls2 = _install_session_post(
        monkeypatch, {"choices": [{"message": {"content": _GOOD_JSON}}]}
    )
    CloudProvider(
        CloudConfig(api_key=SECRET, model="openai/gpt-4o-mini", base_url="https://openrouter.ai/api/v1")
    ).summarize(subject="s", body="b")
    assert calls2[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls2[0]["headers"] == {
        "Authorization": f"Bearer {SECRET}",
        "Content-Type": "application/json",
        "X-Title": "WebmailSummary",
    }
    assert calls2[0]["timeout"] == 120
