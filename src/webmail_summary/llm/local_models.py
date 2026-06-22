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
    group: str = "recommended"  # "recommended" | "korean_nc" | "legacy" | "mlx"
    engine: str = "gguf"  # "gguf" | "mlx"
    min_engine_build: int = 0  # deprecated: engine auto-updates to latest
    license: str = ""  # short license label (e.g. "MIT", "Apache-2.0")
    commercial: bool = True  # False = non-commercial / personal·research only
    min_ram_gb: float = 0.0  # recommended minimum total RAM (GB)


# 2026-06-22: 8코어 CPU 실측 벤치(동일 한국어 메일 요약)로 tier별 1종만 남김.
#   빠름  EXAONE 4.0 1.2B   약 39.5 tok/s  (압도적 속도, 짧은 메일에 충분)
#   표준  Gemma 3 4B        약 15.6 tok/s  (속도·품질 균형, 깔끔한 요약)
#   성능  Qwen3 4B 2507     약 12.9 tok/s  (가장 충실한 요약, 다국어 강함)
# (Mi:dm Mini·Gemma 4 E2B는 CPU 추론이 비정상적으로 느려 제외. MLX·기타 정리.)
LOCAL_MODELS: list[LocalModelChoice] = [
    LocalModelChoice(
        id="fast",
        label="빠름 — EXAONE 4.0 1.2B (Q4_K_M)",
        tier="fast",
        hf_repo_id="LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF",
        hf_filename="EXAONE-4.0-1.2B-Q4_K_M.gguf",
        notes="LG EXAONE 4.0 1.2B. 가장 빠름(8코어 CPU 약 40 tok/s). RAM 4GB에서도 동작. 짧은 메일 요약에 충분.",
        group="recommended",
        license="EXAONE",
        commercial=False,
        min_ram_gb=4.0,
    ),
    LocalModelChoice(
        id="standard",
        label="표준 — Gemma 3 4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="bartowski/google_gemma-3-4b-it-GGUF",
        hf_filename="google_gemma-3-4b-it-Q4_K_M.gguf",
        notes="Gemma 3 4B. 속도와 품질의 균형. 핵심·마감·금액을 안정적으로 잡는 깔끔한 요약. RAM 8GB 권장.",
        group="recommended",
        license="Gemma",
        commercial=True,
        min_ram_gb=8.0,
    ),
    LocalModelChoice(
        id="performance",
        label="성능 — Qwen3 4B Instruct 2507 (Q4_K_M)",
        tier="performance",
        hf_repo_id="unsloth/Qwen3-4B-Instruct-2507-GGUF",
        hf_filename="Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        notes="Qwen3 4B(텍스트 전용). 가장 충실한 요약과 다국어 성능. 4B라 다소 느리지만 정확도 우선일 때. RAM 8GB 권장.",
        group="recommended",
        license="Apache-2.0",
        commercial=True,
        min_ram_gb=8.0,
    ),
]

# Models grouped for UI rendering. (현재는 추천 3종만 운영, 나머지 그룹은 비어 있음)
RECOMMENDED_MODELS = [m for m in LOCAL_MODELS if m.group == "recommended"]
KOREAN_NC_MODELS = [m for m in LOCAL_MODELS if m.group == "korean_nc"]
LEGACY_MODELS = [m for m in LOCAL_MODELS if m.group == "legacy"]
MLX_MODELS = [m for m in LOCAL_MODELS if m.group == "mlx"]
GGUF_MODELS = [m for m in LOCAL_MODELS if m.engine == "gguf"]

# When the preferred default isn't downloaded yet, fall back to a smaller one
# that runs on tight RAM so existing users are never blocked.
MIGRATION_FALLBACKS: dict[str, str] = {
    "standard": "fast",
    "performance": "fast",
}


# GGUF ↔ MLX 매핑 (현재 MLX 모델 미운영).
_GGUF_TO_MLX: dict[str, str] = {}
_MLX_TO_GGUF: dict[str, str] = {v: k for k, v in _GGUF_TO_MLX.items()}


def get_counterpart_model_id(model_id: str) -> str | None:
    """Return the matching model ID in the other engine, or None."""
    mid = str(model_id or "").strip().lower()
    return _GGUF_TO_MLX.get(mid) or _MLX_TO_GGUF.get(mid)


def recommend_local_model() -> LocalModelChoice:
    """Default model for new installs.

    8GB+ 노트북이면 균형 좋은 표준(Gemma 3 4B), RAM이 빠듯하면 빠름(EXAONE 4.0 1.2B).
    """
    try:
        total_gb = psutil.virtual_memory().total / (1024**3)
    except Exception:
        total_gb = 16.0

    by_id = {m.id: m for m in LOCAL_MODELS}
    for fid in ("standard", "fast", "performance"):
        m = by_id.get(fid)
        if m is not None and total_gb >= float(m.min_ram_gb or 0):
            return m
    return by_id.get("fast") or LOCAL_MODELS[0]


def get_local_model(model_id: str) -> LocalModelChoice:
    mid = str(model_id or "").strip().lower()
    # Backward compatibility: 옛 저장 ID를 현재 3종(fast/standard/performance)으로 이관.
    aliases = {
        "low": "performance",
        "ultra": "standard",
        # 제거된 모델 → 가장 가까운 생존 tier
        "midm_mini": "fast",
        "exaone40_1.2b": "fast",
        "exaone35_2.4b": "fast",
        "kanana_nano": "fast",
        "gemma4_e2b": "standard",
        "gemma4_e4b": "standard",
        "qwen35_4b": "performance",
        "qwen3_4b": "performance",
        # 제거된 MLX 항목 → GGUF 대응
        "mlx_fast": "fast",
        "mlx_standard": "standard",
        "mlx_gemma4_e4b": "standard",
        "mlx_qwen35_4b": "performance",
    }
    mid = aliases.get(mid, mid)

    for m in LOCAL_MODELS:
        if m.id == mid:
            return m
    return recommend_local_model()
