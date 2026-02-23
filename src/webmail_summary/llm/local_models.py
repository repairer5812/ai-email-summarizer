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
        label="빠름 — Gemma 2 2B (Q4_K_M)",
        tier="fast",
        hf_repo_id="bartowski/gemma-2-2b-it-GGUF",
        hf_filename="gemma-2-2b-it-Q4_K_M.gguf",
        notes="작지만 매우 똑똑한 구글 모델입니다. 속도와 지능의 균형이 우수합니다.",
    ),
    LocalModelChoice(
        id="standard",
        label="표준 — EXAONE 3.5 2.4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF",
        hf_filename="EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf",
        notes="한국어 요약 품질을 우선하는 기본 모델입니다.",
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
        if m.id == "standard":
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
