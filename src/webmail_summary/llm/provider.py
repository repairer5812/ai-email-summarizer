from __future__ import annotations

import logging
from dataclasses import dataclass
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

log = logging.getLogger(__name__)


class LlmNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalTierBudget:
    max_tokens: int
    request_timeout_s: float
    total_request_budget_s: float


def _local_tier_budget(tier: str) -> LocalTierBudget:
    tier_norm = str(tier or "").strip().lower()
    if tier_norm == "fast":
        return LocalTierBudget(
            max_tokens=384,
            request_timeout_s=120.0,
            total_request_budget_s=240.0,
        )
    if tier_norm == "performance":
        return LocalTierBudget(
            max_tokens=512,
            request_timeout_s=210.0,
            total_request_budget_s=420.0,
        )
    # Standard now points at 4B-class models, so give it more room than fast
    # while keeping performance as the largest local tier.
    return LocalTierBudget(
        max_tokens=448,
        request_timeout_s=180.0,
        total_request_budget_s=360.0,
    )


def _find_llama_server_sibling(cli_path):
    for name in ["llama-server.exe", "llama-server"]:
        candidate = cli_path.with_name(name)
        if candidate.exists():
            return candidate
    return None


def _resolve_engine(settings: Settings) -> str:
    """Resolve the effective engine: ``"mlx"`` or ``"llamacpp"``."""
    engine = getattr(settings, "local_engine", "auto") or "auto"
    engine = engine.strip().lower()
    if engine == "mlx":
        return "mlx"
    if engine == "llamacpp":
        return "llamacpp"
    # "auto": prefer MLX on Apple Silicon.
    from webmail_summary.util.platform_caps import is_apple_silicon

    if is_apple_silicon():
        from webmail_summary.llm.mlx_engine import find_mlx_installed

        if find_mlx_installed() is not None:
            return "mlx"
    return "llamacpp"


def _try_mlx_provider(settings: Settings) -> LlmProvider | None:
    """Attempt to create an MLX provider.  Returns None on failure."""
    try:
        from webmail_summary.llm.local_models import get_local_model
        from webmail_summary.llm.mlx_engine import find_mlx_installed
        from webmail_summary.llm.mlx_server import MlxServerConfig, MlxServerProvider

        mlx_inst = find_mlx_installed()
        if mlx_inst is None:
            log.warning("MLX engine selected but mlx-lm not installed; falling back to llama.cpp")
            return None

        model_choice = get_local_model(settings.local_model_id)
        tier = model_choice.tier if hasattr(model_choice, "tier") else "standard"

        # If user has an MLX model selected, use it directly.
        # If user has a GGUF model selected, try to find the MLX counterpart.
        hf_repo = model_choice.hf_repo_id
        if model_choice.engine != "mlx":
            from webmail_summary.llm.local_models import get_counterpart_model_id, get_local_model

            counterpart_id = get_counterpart_model_id(model_choice.id)
            if counterpart_id:
                counterpart = get_local_model(counterpart_id)
                hf_repo = counterpart.hf_repo_id
                log.info("MLX engine: mapped %s → %s", model_choice.id, counterpart_id)
            else:
                log.warning("No MLX counterpart for model %s; falling back to llama.cpp", model_choice.id)
                return None

        budget = _local_tier_budget(tier)
        cfg = MlxServerConfig(
            mlx_install=mlx_inst,
            hf_repo_id=hf_repo,
            max_tokens=budget.max_tokens,
            request_timeout_s=budget.request_timeout_s,
            total_request_budget_s=budget.total_request_budget_s,
        )
        return MlxServerProvider(cfg, tier=tier)
    except Exception as e:
        log.warning("Failed to create MLX provider: %s", e)
        return None


def get_llm_provider(settings: Settings) -> LlmProvider:
    backend = (settings.llm_backend or "local").strip().lower()

    if backend == "local":
        # --- MLX path ---
        engine = _resolve_engine(settings)
        if engine == "mlx":
            mlx_prov = _try_mlx_provider(settings)
            if mlx_prov is not None:
                return mlx_prov
            log.info("MLX provider unavailable; falling back to llama.cpp")

        # --- llama.cpp path (original) ---
        inst = find_llama_cpp_installed()
        if inst is None:
            raise LlmNotReady("Local engine not installed")

        from webmail_summary.llm.local_models import get_local_model, MIGRATION_FALLBACKS

        model_choice = get_local_model(settings.local_model_id)
        tier = model_choice.tier if hasattr(model_choice, "tier") else "standard"

        # If model is MLX-only but we fell back to llama.cpp, find GGUF counterpart.
        if model_choice.engine == "mlx":
            from webmail_summary.llm.local_models import get_counterpart_model_id

            counterpart_id = get_counterpart_model_id(model_choice.id)
            if counterpart_id:
                model_choice = get_local_model(counterpart_id)
            else:
                raise LlmNotReady("Selected MLX model has no GGUF fallback")

        model_path = get_local_model_path(model_id=model_choice.id)
        complete = get_local_model_complete_marker(model_id=model_choice.id)
        if not model_path.exists() or not complete.exists():
            # Migration fallback: if the new default model is not installed yet,
            # try to use the previous model so existing users are not blocked.
            fallback_id = MIGRATION_FALLBACKS.get(model_choice.id)
            if fallback_id:
                fb = get_local_model(fallback_id)
                fb_path = get_local_model_path(model_id=fb.id)
                fb_marker = get_local_model_complete_marker(model_id=fb.id)
                if fb_path.exists() and fb_marker.exists():
                    log.info(
                        "Model %s not installed; falling back to %s",
                        model_choice.id, fb.id,
                    )
                    model_choice = fb
                    model_path = fb_path
                    complete = fb_marker
                    tier = fb.tier
            if not model_path.exists() or not complete.exists():
                raise LlmNotReady("Local model not installed")

        # Prefer persistent llama-server to avoid reloading the model per email.
        server_exe = _find_llama_server_sibling(inst.llama_cli_path)
        if server_exe is not None:
            try:
                # Local llama-server can be slow on some machines.
                # Use generous timeouts and allow a retry (we restart the server on timeout).
                budget = _local_tier_budget(tier)
                max_attempts = 2
                return LlamaCppServerProvider(
                    LlamaCppServerConfig(
                        server_exe=server_exe,
                        model_path=model_path,
                        max_tokens=int(budget.max_tokens),
                        request_timeout_s=float(budget.request_timeout_s),
                        max_attempts=int(max_attempts),
                        total_request_budget_s=float(
                            budget.total_request_budget_s
                        ),
                    ),
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
        selected_model = (settings.openrouter_model or "").strip()

        # Map internal provider names to base URLs and models
        # OpenAI, Google, Upstage are OpenAI-compatible.
        # Anthropic would need a separate adapter if we use their native SDK,
        # but for now we recommend OpenRouter for Anthropic or stick to OpenAI-compatible ones.
        defaults = {
            "openai": "gpt-4o-mini",
            "google": "gemini-2.5-flash",
            "upstage": "solar-mini",
            "anthropic": "claude-3-5-haiku-20241022",
            "openrouter": "openai/gpt-4o-mini",
        }
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "google": "https://generativelanguage.googleapis.com",
            "upstage": "https://api.upstage.ai/v1/solar",
            "anthropic": "https://api.anthropic.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
        }

        if provider_name not in base_urls:
            provider_name = "openai"

        base_url = base_urls[provider_name]
        model = selected_model or defaults[provider_name]
        api_key_service = f"webmail-summary::{provider_name}"
        api_key = keyring.get_password(api_key_service, "api_key")

        if not api_key:
            raise LlmNotReady(f"{provider_name.upper()} API key not set in setup")

        return CloudProvider(
            CloudConfig(api_key=api_key, model=model, base_url=base_url)
        )

    raise LlmNotReady(f"Unsupported LLM backend: {backend}")
