from __future__ import annotations

from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class LlmModelChoice:
    id: str
    label: str
    tier: str
    notes: str


LLM_MODELS: list[LlmModelChoice] = [
    LlmModelChoice(
        id="exaone3.5:2.4b",
        label="Low — EXAONE 3.5 2.4B (Korean/English)",
        tier="low",
        notes="Lightweight. Good Korean summaries on 16GB.",
    ),
    LlmModelChoice(
        id="exaone3.5:7.8b",
        label="Medium — EXAONE 3.5 7.8B (Korean/English)",
        tier="medium",
        notes="Better quality. Recommended default on 16–32GB.",
    ),
    LlmModelChoice(
        id="qwen2.5:14b-instruct-q3_K_S",
        label="High — Qwen2.5 14B (Q3_K_S)",
        tier="high",
        notes="Higher quality but heavier. Best on 32GB.",
    ),
]


def recommend_model() -> LlmModelChoice:
    mem_gb = psutil.virtual_memory().total / (1024**3)
    if mem_gb < 20:
        return LLM_MODELS[0]
    if mem_gb < 28:
        return LLM_MODELS[1]
    return LLM_MODELS[2]
