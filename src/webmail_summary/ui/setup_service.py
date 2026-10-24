from __future__ import annotations

import keyring
import requests

from webmail_summary.index.settings import Settings
from webmail_summary.llm.cloud_registry import (
    ANTHROPIC_MESSAGES_URL,
    API_ANTHROPIC,
    API_GEMINI,
    KEYRING_USERNAME,
    PROVIDER_IDS,
    PROVIDERS,
    anthropic_headers,
    chat_completions_url,
    gemini_generate_content_url,
    gemini_headers,
    get_provider,
    keyring_service,
    openai_compatible_headers,
)
from webmail_summary.llm.local_status import check_local_ready


def get_cloud_keys() -> dict[str, bool]:
    cloud_keys = {}
    for p in PROVIDER_IDS:
        try:
            val = keyring.get_password(keyring_service(p), KEYRING_USERNAME)
            cloud_keys[p] = bool(val and val.strip())
        except Exception:
            cloud_keys[p] = False
    return cloud_keys


def _ping_openai_compatible(url: str, headers: dict[str, str], model: str):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 8,
    }
    return requests.post(url, headers=headers, json=payload, timeout=25)


def test_cloud_api_key(
    provider_name: str, api_key: str, model: str
) -> tuple[bool, str]:
    provider = (provider_name or "openai").strip().lower()
    spec = get_provider(provider)
    chosen_model = (model or "").strip()
    selected_model = chosen_model or (
        spec.default_model if spec else PROVIDERS["openai"].default_model
    )

    try:
        if spec is None:
            return False, "실패: 지원하지 않는 클라우드 제공자입니다."

        if spec.api == API_GEMINI:
            payload = {
                "contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8},
            }
            r = requests.post(
                gemini_generate_content_url(selected_model),
                headers=gemini_headers(api_key),
                json=payload,
                timeout=25,
            )
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Google API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Google API 오류 {r.status_code}"

        if spec.api == API_ANTHROPIC:
            payload = {
                "model": selected_model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            }
            r = requests.post(
                ANTHROPIC_MESSAGES_URL,
                headers=anthropic_headers(api_key),
                json=payload,
                timeout=25,
            )
            if r.status_code == 200:
                return (
                    True,
                    f"성공: Anthropic API 키가 유효합니다. (모델: {selected_model})",
                )
            return False, f"실패: Anthropic API 오류 {r.status_code}"

        headers = openai_compatible_headers(api_key, base_url=spec.base_url)
        if spec.key_test_urls:
            # Upstage: try both chat endpoints and the fallback models.
            model_candidates = [selected_model]
            for m in spec.key_test_models:
                if m not in model_candidates:
                    model_candidates.append(m)

            last_code = 0
            for test_url in spec.key_test_urls:
                for test_model in model_candidates:
                    r = _ping_openai_compatible(test_url, headers, test_model)
                    last_code = r.status_code
                    if r.status_code == 200:
                        return (
                            True,
                            f"성공: UPSTAGE API 키가 유효합니다. (모델: {test_model})",
                        )
                    if r.status_code in {401, 403}:
                        return False, "실패: Upstage API 키 인증에 실패했습니다."
            return False, f"실패: Upstage API 오류 {last_code}"

        r = _ping_openai_compatible(
            chat_completions_url(spec.base_url), headers, selected_model
        )
        if r.status_code == 200:
            return (
                True,
                f"성공: {provider.upper()} API 키가 유효합니다. (모델: {selected_model})",
            )
        if r.status_code in {401, 403}:
            return False, f"실패: {provider.upper()} API 키 인증에 실패했습니다."
        return False, f"실패: {provider.upper()} API 오류 {r.status_code}"
    except Exception:
        return False, "실패: API 테스트 중 네트워크 오류가 발생했습니다. 네트워크 연결 또는 API 엔드포인트 상태를 확인해 주세요."


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
