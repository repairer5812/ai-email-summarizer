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


LOCAL_MODELS: list[LocalModelChoice] = [
    LocalModelChoice(
        id="fast",
        label="빠름 — EXAONE 3.5 2.4B (Q4_K_M)",
        tier="fast",
        hf_repo_id="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF",
        hf_filename="EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf",
        notes="EXAONE 3.5 2.4B 모델입니다. 가장 빠른 응답을 목표로 합니다.",
    ),
    LocalModelChoice(
        id="standard",
        label="표준 — Gemma 3 4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="bartowski/google_gemma-3-4b-it-GGUF",
        hf_filename="google_gemma-3-4b-it-Q4_K_M.gguf",
        notes="Gemma 3 4B 모델입니다. 빠름 대비 더 안정적인 균형 품질을 목표로 합니다.",
    ),
    LocalModelChoice(
        id="performance",
        label="성능 — Qwen2.5 3B (Q4_K_M)",
        tier="performance",
        hf_repo_id="bartowski/Qwen2.5-3B-Instruct-GGUF",
        hf_filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        notes="속도를 조금 더 우선합니다. 짧은 메일에서 빠르게 동작합니다.",
    ),
]


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
