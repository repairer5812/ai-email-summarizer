from __future__ import annotations

import keyring

from webmail_summary.index.settings import Settings
from webmail_summary.llm.base import LlmProvider
from webmail_summary.llm.llamacpp_bin import LlamaCppBinConfig, LlamaCppBinProvider
from webmail_summary.llm.local_engine import find_llama_cpp_installed
from webmail_summary.llm.llamacpp_server import (
    LlamaCppServerConfig,
    LlamaCppServerProvider,
)
from webmail_summary.llm.local_status import (
    get_local_model_complete_marker,
    get_local_model_path,
)
from webmail_summary.llm.openrouter import CloudConfig, CloudProvider


class LlmNotReady(RuntimeError):
    pass


def get_llm_provider(settings: Settings) -> LlmProvider:
    backend = (settings.llm_backend or "local").strip().lower()

    if backend == "local":
        inst = find_llama_cpp_installed()
        if inst is None:
            raise LlmNotReady("Local engine not installed")

        from webmail_summary.llm.local_models import get_local_model

        model_choice = get_local_model(settings.local_model_id)
        tier = model_choice.tier if hasattr(model_choice, "tier") else "standard"

        model_path = get_local_model_path(model_id=settings.local_model_id)
        complete = get_local_model_complete_marker(model_id=settings.local_model_id)
        if not model_path.exists() or not complete.exists():
            raise LlmNotReady("Local model not installed")

        # Prefer persistent llama-server to avoid reloading the model per email.
        server_exe = inst.llama_cli_path.with_name("llama-server.exe")
        if server_exe.exists():
            try:
                return LlamaCppServerProvider(
                    LlamaCppServerConfig(server_exe=server_exe, model_path=model_path),
                    tier=tier,
                )
            except Exception:
                pass

        return LlamaCppBinProvider(
            LlamaCppBinConfig(
                llama_cli_path=inst.llama_cli_path, model_path=model_path
            ),
            tier=tier,
        )

    if backend == "openrouter" or backend == "cloud":
        provider_name = (settings.cloud_provider or "openai").strip().lower()

        # Map internal provider names to base URLs and models
        # OpenAI, Google, Upstage are OpenAI-compatible.
        # Anthropic would need a separate adapter if we use their native SDK,
        # but for now we recommend OpenRouter for Anthropic or stick to OpenAI-compatible ones.
        configs = {
            "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "google": (
                "https://generativelanguage.googleapis.com",
                "gemini-2.5-flash",
            ),
            "upstage": ("https://api.upstage.ai/v1/solar", "solar-mini"),
            "anthropic": ("https://api.anthropic.com/v1", "claude-3-5-haiku-20241022"),
            "openrouter": ("https://openrouter.ai/api/v1", settings.openrouter_model),
        }

        if provider_name not in configs:
            provider_name = "openai"

        base_url, model = configs[provider_name]
        api_key_service = f"webmail-summary::{provider_name}"
        api_key = keyring.get_password(api_key_service, "api_key")

        if not api_key:
            raise LlmNotReady(f"{provider_name.upper()} API key not set in setup")

        return CloudProvider(
            CloudConfig(api_key=api_key, model=model, base_url=base_url)
        )

    raise LlmNotReady(f"Unsupported LLM backend: {backend}")
