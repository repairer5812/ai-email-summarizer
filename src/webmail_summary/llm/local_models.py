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
    group: str = "recommended"  # "recommended" | "legacy"


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
        id="gemma4_e4b",
        label="표준 — Gemma 4 E4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="unsloth/gemma-4-E4B-it-GGUF",
        hf_filename="gemma-4-E4B-it-Q4_K_M.gguf",
        notes="Gemma 4 E4B 모델입니다. 추론·코딩 성능이 크게 향상된 최신 모델입니다.",
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
        id="standard",
        label="기존 — Gemma 3 4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="bartowski/google_gemma-3-4b-it-GGUF",
        hf_filename="google_gemma-3-4b-it-Q4_K_M.gguf",
        notes="Gemma 3 4B 모델입니다. 안정적인 균형 품질.",
        group="legacy",
    ),
    LocalModelChoice(
        id="performance",
        label="기존 — Qwen 2.5 3B (Q4_K_M)",
        tier="performance",
        hf_repo_id="bartowski/Qwen2.5-3B-Instruct-GGUF",
        hf_filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        notes="Qwen 2.5 3B 모델입니다. 짧은 메일에서 빠르게 동작합니다.",
        group="legacy",
    ),
]

# Models grouped for UI rendering.
RECOMMENDED_MODELS = [m for m in LOCAL_MODELS if m.group == "recommended"]
LEGACY_MODELS = [m for m in LOCAL_MODELS if m.group == "legacy"]


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
    }
    mid = aliases.get(mid, mid)

    for m in LOCAL_MODELS:
        if m.id == mid:
            return m
    return recommend_local_model()
