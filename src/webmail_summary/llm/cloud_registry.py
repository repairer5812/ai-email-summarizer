"""Cloud LLM providers: one table plus the endpoint and header builders.

The provider factory (llm/provider.py), the setup key test
(ui/setup_service.py) and the cloud request code (llm/openrouter.py) used to
keep their own copies of the base URLs, default models and auth headers.
They all read from here now.
"""

from __future__ import annotations

from dataclasses import dataclass

# Request shapes. OpenAI, Upstage and OpenRouter share the OpenAI
# chat/completions format; Anthropic and Gemini use their native APIs.
API_OPENAI = "openai"
API_ANTHROPIC = "anthropic"
API_GEMINI = "gemini"


@dataclass(frozen=True)
class CloudProviderSpec:
    id: str
    base_url: str
    default_model: str
    api: str
    # Extra chat/completions endpoints and models tried by the setup key test.
    key_test_urls: tuple[str, ...] = ()
    key_test_models: tuple[str, ...] = ()


DEFAULT_PROVIDER_ID = "openai"

# Order matches the setup screen and get_cloud_keys().
PROVIDERS: dict[str, CloudProviderSpec] = {
    "openai": CloudProviderSpec(
        id="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        api=API_OPENAI,
    ),
    "anthropic": CloudProviderSpec(
        id="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-haiku-20241022",
        api=API_ANTHROPIC,
    ),
    "google": CloudProviderSpec(
        id="google",
        base_url="https://generativelanguage.googleapis.com",
        default_model="gemini-2.5-flash",
        api=API_GEMINI,
    ),
    "upstage": CloudProviderSpec(
        id="upstage",
        base_url="https://api.upstage.ai/v1/solar",
        default_model="solar-mini",
        api=API_OPENAI,
        key_test_urls=(
            "https://api.upstage.ai/v1/solar/chat/completions",
            "https://api.upstage.ai/v1/chat/completions",
        ),
        key_test_models=("solar-mini", "solar-pro"),
    ),
    "openrouter": CloudProviderSpec(
        id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        api=API_OPENAI,
    ),
}

PROVIDER_IDS: tuple[str, ...] = tuple(PROVIDERS)

KEYRING_USERNAME = "api_key"

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

_GEMINI_HOST = "generativelanguage.googleapis.com"
_ANTHROPIC_HOST = "api.anthropic.com"
_OPENROUTER_HOST = "openrouter.ai"


def normalize_provider_id(provider_id: str | None) -> str:
    return str(provider_id or DEFAULT_PROVIDER_ID).strip().lower()


def get_provider(provider_id: str | None) -> CloudProviderSpec | None:
    return PROVIDERS.get(normalize_provider_id(provider_id))


def resolve_provider(provider_id: str | None) -> CloudProviderSpec:
    """Like get_provider, but unknown ids fall back to the default provider."""
    return get_provider(provider_id) or PROVIDERS[DEFAULT_PROVIDER_ID]


def keyring_service(provider_id: str) -> str:
    return f"webmail-summary::{provider_id}"


def api_for_base_url(base_url: str | None) -> str:
    base = str(base_url or "")
    if _GEMINI_HOST in base:
        return API_GEMINI
    if _ANTHROPIC_HOST in base:
        return API_ANTHROPIC
    return API_OPENAI


def chat_completions_url(base_url: str) -> str:
    return f"{base_url}/chat/completions"


def openai_compatible_headers(api_key: str, *, base_url: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if _OPENROUTER_HOST in str(base_url or ""):
        headers["X-Title"] = "WebmailSummary"
    return headers


def anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def gemini_generate_content_url(model: str) -> str:
    """generateContent endpoint. The key goes in a header, never the URL."""
    model_id = str(model or "")
    if not model_id.startswith("models/"):
        model_id = f"models/{model_id}"
    return f"{GEMINI_API_BASE}/{model_id}:generateContent"


def gemini_headers(api_key: str) -> dict[str, str]:
    # Google documents x-goog-api-key as the preferred way to send an API key;
    # a ?key= query parameter ends up in proxy and server logs.
    return {"x-goog-api-key": api_key}
