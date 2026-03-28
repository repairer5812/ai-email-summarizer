from __future__ import annotations

import keyring
import requests

from webmail_summary.index.settings import Settings
from webmail_summary.llm.local_status import check_local_ready


def get_cloud_keys() -> dict[str, bool]:
    cloud_keys = {}
    for p in ["openai", "anthropic", "google", "upstage", "openrouter"]:
        try:
            svc = f"webmail-summary::{p}"
            val = keyring.get_password(svc, "api_key")
            cloud_keys[p] = bool(val and val.strip())
        except Exception:
            cloud_keys[p] = False
    return cloud_keys


def test_cloud_api_key(
    provider_name: str, api_key: str, model: str
) -> tuple[bool, str]:
    provider = (provider_name or "openai").strip().lower()
    chosen_model = (model or "").strip()

    defaults = {
        "openai": "gpt-4o-mini",
        "google": "gemini-2.5-flash",
        "upstage": "solar-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "openrouter": "openai/gpt-4o-mini",
    }
    selected_model = chosen_model or defaults.get(provider, "gpt-4o-mini")

    try:
        if provider == "google":
            model_id = selected_model
            if not model_id.startswith("models/"):
                model_id = f"models/{model_id}"
            url = f"https://generativelanguage.googleapis.com/v1beta/{model_id}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8},
            }
            r = requests.post(url, json=payload, timeout=25)
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Google API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Google API 오류 {r.status_code}"

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": selected_model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            }
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Anthropic API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Anthropic API 오류 {r.status_code}"

        base_urls = {
            "openai": "https://api.openai.com/v1",
            "upstage": "https://api.upstage.ai/v1/solar",
            "openrouter": "https://openrouter.ai/api/v1",
        }
        if provider not in base_urls:
            return False, "실패: 지원하지 않는 클라우드 제공자입니다."

        url = f"{base_urls[provider]}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["X-Title"] = "WebmailSummary"
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 8,
        }
        if provider == "upstage":
            upstage_urls = [
                "https://api.upstage.ai/v1/solar/chat/completions",
                "https://api.upstage.ai/v1/chat/completions",
            ]
            model_candidates = [selected_model]
            for m in ["solar-mini", "solar-pro"]:
                if m not in model_candidates:
                    model_candidates.append(m)

            last_code = 0
            for test_url in upstage_urls:
                for test_model in model_candidates:
                    test_payload = {
                        "model": test_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "temperature": 0,
                        "max_tokens": 8,
                    }
                    r = requests.post(
                        test_url, headers=headers, json=test_payload, timeout=25
                    )
                    last_code = r.status_code
                    if r.status_code == 200:
                        return (
                            True,
                            f"성공: UPSTAGE API 키가 유효합니다. (모델: {test_model})",
                        )
                    if r.status_code in {401, 403}:
                        return False, "실패: Upstage API 키 인증에 실패했습니다."
            return False, f"실패: Upstage API 오류 {last_code}"

        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code == 200:
            return (
                True,
                f"성공: {provider.upper()} API 키가 유효합니다. (모델: {selected_model})",
            )
        if r.status_code in {401, 403}:
            return False, f"실패: {provider.upper()} API 키 인증에 실패했습니다."
        return False, f"실패: {provider.upper()} API 오류 {r.status_code}"
    except Exception as e:
        return False, f"실패: API 테스트 중 예외가 발생했습니다. ({str(e)[:120]})"


def pick_directory_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select Folder")
        root.destroy()
        return str(path) if path else None
    except Exception:
        return None


def is_ai_ready(settings: Settings) -> bool:
    backend = (settings.llm_backend or "local").strip().lower()
    if backend == "local":
        ready = check_local_ready(model_id=settings.local_model_id)
        return ready.engine_ok and ready.model_ok
    if backend in {"openrouter", "cloud"}:
        provider_name = (settings.cloud_provider or "openai").strip().lower()
        keys = get_cloud_keys()
        return keys.get(provider_name, False)
    return False


def is_setup_complete(settings: Settings) -> bool:
    if not settings.imap_host or not settings.imap_user:
        return False
    return is_ai_ready(settings)
