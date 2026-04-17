from __future__ import annotations

from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class LocalModelChoice:
    id: str
    label: str
    tier: str
    hf_repo_id: str
    hf_filename: str
    notes: str
    group: str = "recommended"  # "recommended" | "legacy" | "mlx"
    engine: str = "gguf"  # "gguf" | "mlx"
    min_engine_build: int = 0  # deprecated: engine auto-updates to latest


LOCAL_MODELS: list[LocalModelChoice] = [
    # ── 추천 모델 (Recommended) ──────────────────────────
    LocalModelChoice(
        id="fast",
        label="빠름 — EXAONE 3.5 2.4B (Q4_K_M)",
        tier="fast",
        hf_repo_id="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF",
        hf_filename="EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf",
        notes="EXAONE 3.5 2.4B 모델입니다. 가장 빠른 응답, 한국어 특화.",
        group="recommended",
    ),
    LocalModelChoice(
        id="standard",
        label="표준 — Gemma 3 4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="bartowski/google_gemma-3-4b-it-GGUF",
        hf_filename="google_gemma-3-4b-it-Q4_K_M.gguf",
        notes="Gemma 3 4B 모델입니다. 안정적인 균형 품질.",
        group="recommended",
    ),
    LocalModelChoice(
        id="qwen35_4b",
        label="성능 — Qwen 3.5 4B (Q4_K_M)",
        tier="performance",
        hf_repo_id="unsloth/Qwen3.5-4B-GGUF",
        hf_filename="Qwen3.5-4B-Q4_K_M.gguf",
        notes="Qwen 3.5 4B 모델입니다. 다국어·코딩 성능이 우수한 최신 모델입니다.",
        group="recommended",
    ),
    # ── 기존 모델 (Legacy) ───────────────────────────────
    LocalModelChoice(
        id="performance",
        label="기존 — Qwen 2.5 3B (Q4_K_M)",
        tier="performance",
        hf_repo_id="bartowski/Qwen2.5-3B-Instruct-GGUF",
        hf_filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        notes="Qwen 2.5 3B 모델입니다. 짧은 메일에서 빠르게 동작합니다.",
        group="legacy",
    ),
    # ── MLX 모델 (Apple Silicon 전용) ────────────────────
    LocalModelChoice(
        id="mlx_fast",
        label="MLX 빠름 — EXAONE 3.5 2.4B (4bit)",
        tier="fast",
        hf_repo_id="mlx-community/EXAONE-3.5-2.4B-Instruct-4bit",
        hf_filename="",  # MLX: repo 전체를 다운로드
        notes="Apple Silicon 전용. EXAONE 3.5 2.4B MLX 최적화 모델. 한국어 특화.",
        group="mlx",
        engine="mlx",
    ),
    LocalModelChoice(
        id="mlx_standard",
        label="MLX 표준 — Gemma 3 4B (4bit)",
        tier="standard",
        hf_repo_id="mlx-community/gemma-3-4b-it-4bit",
        hf_filename="",
        notes="Apple Silicon 전용. Gemma 3 4B MLX 최적화 모델.",
        group="mlx",
        engine="mlx",
    ),
    LocalModelChoice(
        id="mlx_qwen35_4b",
        label="MLX 성능 — Qwen 3.5 4B (4bit)",
        tier="performance",
        hf_repo_id="mlx-community/Qwen3.5-4B-MLX-4bit",
        hf_filename="",
        notes="Apple Silicon 전용. Qwen 3.5 4B MLX 최적화 모델.",
        group="mlx",
        engine="mlx",
    ),
]

# Models grouped for UI rendering.
RECOMMENDED_MODELS = [m for m in LOCAL_MODELS if m.group == "recommended"]
LEGACY_MODELS = [m for m in LOCAL_MODELS if m.group == "legacy"]
MLX_MODELS = [m for m in LOCAL_MODELS if m.group == "mlx"]
GGUF_MODELS = [m for m in LOCAL_MODELS if m.engine == "gguf"]

# When a new default model is not yet installed, fall back to the previous one.
# key = new model id, value = legacy model id to use as fallback.
MIGRATION_FALLBACKS: dict[str, str] = {
    # No active migration fallbacks needed.
    # EXAONE 3.5 2.4B is back as the default "fast" model.
}


# GGUF ↔ MLX model mapping for automatic engine switching.
_GGUF_TO_MLX: dict[str, str] = {
    "fast": "mlx_fast",
    "standard": "mlx_standard",
    "qwen35_4b": "mlx_qwen35_4b",
}
_MLX_TO_GGUF: dict[str, str] = {v: k for k, v in _GGUF_TO_MLX.items()}


def get_counterpart_model_id(model_id: str) -> str | None:
    """Return the matching model ID in the other engine, or None."""
    mid = str(model_id or "").strip().lower()
    return _GGUF_TO_MLX.get(mid) or _MLX_TO_GGUF.get(mid)


def recommend_local_model() -> LocalModelChoice:
    _ = psutil
    for m in LOCAL_MODELS:
        if m.id == "fast":
            return m
    return LOCAL_MODELS[0]


def get_local_model(model_id: str) -> LocalModelChoice:
    mid = str(model_id or "").strip().lower()
    # Backward compatibility for older saved IDs.
    aliases = {
        "low": "performance",
        "ultra": "standard",
        "exaone40_1.2b": "fast",     # removed model → fallback to default
        "gemma4_e4b": "standard",    # Gemma 4 E4B → Gemma 3 4B
        "exaone35_2.4b": "fast",     # legacy ID
        "mlx_gemma4_e4b": "mlx_standard",  # MLX Gemma 4 → MLX Gemma 3
    }
    mid = aliases.get(mid, mid)

    for m in LOCAL_MODELS:
        if m.id == mid:
            return m
    return recommend_local_model()
