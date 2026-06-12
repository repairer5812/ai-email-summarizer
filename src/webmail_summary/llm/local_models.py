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


LOCAL_MODELS: list[LocalModelChoice] = [
    # ── 추천 (상업 사용 가능) ─────────────────────────────
    LocalModelChoice(
        id="midm_mini",
        label="빠름·기본 — KT Mi:dm 2.0 Mini 2.3B (Q4_K_M)",
        tier="fast",
        hf_repo_id="mykor/Midm-2.0-Mini-Instruct-gguf",
        hf_filename="Midm-2.0-Mini-Instruct-Q4_K_M.gguf",
        notes="한국 특화(존댓말·한자어) 2.3B. 한국어 지시이행이 우수하고 8GB에서도 안전. 상업 사용 가능(MIT).",
        group="recommended",
        license="MIT",
        commercial=True,
        min_ram_gb=4.0,
    ),
    LocalModelChoice(
        id="standard",
        label="표준 — Gemma 3 4B (Q4_K_M)",
        tier="standard",
        hf_repo_id="bartowski/google_gemma-3-4b-it-GGUF",
        hf_filename="google_gemma-3-4b-it-Q4_K_M.gguf",
        notes="Gemma 3 4B. 안정적인 균형 품질. 상업 사용 가능(Gemma 라이선스).",
        group="recommended",
        license="Gemma",
        commercial=True,
        min_ram_gb=8.0,
    ),
    LocalModelChoice(
        id="gemma4_e2b",
        label="최신 — Gemma 4 E2B (Q4_K_M)",
        tier="standard",
        hf_repo_id="unsloth/gemma-4-E2B-it-GGUF",
        hf_filename="gemma-4-E2B-it-Q4_K_M.gguf",
        notes="Gemma 4 E2B(실효 2.3B). 최신 세대·140개 언어. 용량이 커 RAM 10GB+ 권장. 상업 사용 가능(Apache-2.0).",
        group="recommended",
        license="Apache-2.0",
        commercial=True,
        min_ram_gb=10.0,
    ),
    LocalModelChoice(
        id="qwen35_4b",
        label="성능 — Qwen3 4B Instruct 2507 (Q4_K_M)",
        tier="performance",
        hf_repo_id="unsloth/Qwen3-4B-Instruct-2507-GGUF",
        hf_filename="Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        notes="Qwen3 4B(텍스트 전용, non-thinking). 다국어 성능 우수, 4B라 다소 느림. 상업 사용 가능(Apache-2.0).",
        group="recommended",
        license="Apache-2.0",
        commercial=True,
        min_ram_gb=8.0,
    ),
    # ── 한국어 특화 (개인·연구용, 비상업 라이선스) ─────────
    LocalModelChoice(
        id="exaone40_1.2b",
        label="초경량 — EXAONE 4.0 1.2B (Q4_K_M)",
        tier="fast",
        hf_repo_id="LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF",
        hf_filename="EXAONE-4.0-1.2B-Q4_K_M.gguf",
        notes="LG EXAONE 4.0 1.2B. 약 1.7~2배 빠르고 RAM도 절반. 비상업(개인·연구용) 라이선스. non-reasoning 모드 권장.",
        group="korean_nc",
        license="EXAONE(비상업)",
        commercial=False,
        min_ram_gb=4.0,
    ),
    LocalModelChoice(
        id="fast",
        label="한국어 — EXAONE 3.5 2.4B (Q4_K_M)",
        tier="fast",
        hf_repo_id="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF",
        hf_filename="EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf",
        notes="LG EXAONE 3.5 2.4B. 한국어 특화. 비상업(개인·연구용) 라이선스.",
        group="korean_nc",
        license="EXAONE(비상업)",
        commercial=False,
        min_ram_gb=6.0,
    ),
    LocalModelChoice(
        id="kanana_nano",
        label="한국어 — Kakao Kanana Nano 2.1B (Q4_K_M)",
        tier="fast",
        hf_repo_id="DevQuasar/kakaocorp.kanana-nano-2.1b-instruct-GGUF",
        hf_filename="kakaocorp.kanana-nano-2.1b-instruct.Q4_K_M.gguf",
        notes="Kakao Kanana Nano 2.1B. 한국어 강함. 비상업(CC-BY-NC-4.0) 라이선스.",
        group="korean_nc",
        license="CC-BY-NC-4.0",
        commercial=False,
        min_ram_gb=4.0,
    ),
    # ── 기존 모델 (Legacy) ───────────────────────────────
    LocalModelChoice(
        id="performance",
        label="기존 — Qwen 2.5 3B (Q4_K_M)",
        tier="performance",
        hf_repo_id="bartowski/Qwen2.5-3B-Instruct-GGUF",
        hf_filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        notes="Qwen 2.5 3B. 짧은 메일에서 빠르게 동작. 상업 사용 가능(Apache-2.0).",
        group="legacy",
        license="Apache-2.0",
        commercial=True,
        min_ram_gb=6.0,
    ),
    # ── MLX 모델 (Apple Silicon 전용) ────────────────────
    LocalModelChoice(
        id="mlx_fast",
        label="MLX 한국어 — EXAONE 3.5 2.4B (4bit)",
        tier="fast",
        hf_repo_id="mlx-community/EXAONE-3.5-2.4B-Instruct-4bit",
        hf_filename="",  # MLX: repo 전체를 다운로드
        notes="Apple Silicon 전용. EXAONE 3.5 2.4B MLX. 한국어 특화. 비상업 라이선스.",
        group="mlx",
        engine="mlx",
        license="EXAONE(비상업)",
        commercial=False,
    ),
    LocalModelChoice(
        id="mlx_standard",
        label="MLX 표준 — Gemma 3 4B (4bit)",
        tier="standard",
        hf_repo_id="mlx-community/gemma-3-4b-it-4bit",
        hf_filename="",
        notes="Apple Silicon 전용. Gemma 3 4B MLX. 상업 사용 가능(Gemma).",
        group="mlx",
        engine="mlx",
        license="Gemma",
        commercial=True,
    ),
]

# Models grouped for UI rendering.
RECOMMENDED_MODELS = [m for m in LOCAL_MODELS if m.group == "recommended"]
KOREAN_NC_MODELS = [m for m in LOCAL_MODELS if m.group == "korean_nc"]
LEGACY_MODELS = [m for m in LOCAL_MODELS if m.group == "legacy"]
MLX_MODELS = [m for m in LOCAL_MODELS if m.group == "mlx"]
GGUF_MODELS = [m for m in LOCAL_MODELS if m.engine == "gguf"]

# When a new default model is not yet installed, fall back to the previous one.
# key = new model id, value = legacy model id to use as fallback.
MIGRATION_FALLBACKS: dict[str, str] = {
    # If the commercial-safe default isn't downloaded yet, fall back to the
    # previously-shipped Korean model so existing users are never blocked.
    "midm_mini": "fast",
}


# GGUF ↔ MLX model mapping for automatic engine switching.
_GGUF_TO_MLX: dict[str, str] = {
    "fast": "mlx_fast",
    "standard": "mlx_standard",
}
_MLX_TO_GGUF: dict[str, str] = {v: k for k, v in _GGUF_TO_MLX.items()}


def get_counterpart_model_id(model_id: str) -> str | None:
    """Return the matching model ID in the other engine, or None."""
    mid = str(model_id or "").strip().lower()
    return _GGUF_TO_MLX.get(mid) or _MLX_TO_GGUF.get(mid)


def recommend_local_model() -> LocalModelChoice:
    """Default model for new installs.

    Commercial-safe (MIT) and small enough for 8GB laptops while staying
    Korean-strong: KT Mi:dm 2.0 Mini.  Falls back down the size ladder if
    RAM is unusually tight or the preferred entry is missing.
    """
    try:
        total_gb = psutil.virtual_memory().total / (1024**3)
    except Exception:
        total_gb = 16.0

    by_id = {m.id: m for m in LOCAL_MODELS}
    # Preference order: commercial-safe first, smallest-safe as last resort.
    for fid in ("midm_mini", "exaone40_1.2b", "fast"):
        m = by_id.get(fid)
        if m is not None and total_gb >= float(m.min_ram_gb or 0):
            return m
    for fid in ("midm_mini", "exaone40_1.2b", "fast"):
        m = by_id.get(fid)
        if m is not None:
            return m
    return LOCAL_MODELS[0]


def get_local_model(model_id: str) -> LocalModelChoice:
    mid = str(model_id or "").strip().lower()
    # Backward compatibility for older saved IDs.
    aliases = {
        "low": "performance",
        "ultra": "standard",
        "gemma4_e4b": "standard",          # old Gemma 4 E4B → Gemma 3 4B
        "exaone35_2.4b": "fast",           # legacy ID → EXAONE 3.5 2.4B
        "qwen3_4b": "qwen35_4b",           # text Qwen3 4B entry
        "mlx_gemma4_e4b": "mlx_standard",  # MLX Gemma 4 → MLX Gemma 3
        "mlx_qwen35_4b": "mlx_standard",   # removed multimodal MLX entry
    }
    mid = aliases.get(mid, mid)

    for m in LOCAL_MODELS:
        if m.id == mid:
            return m
    return recommend_local_model()
