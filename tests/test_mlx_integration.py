"""Tests for MLX engine integration (mock-based, no Apple Silicon required)."""
from __future__ import annotations

import webmail_summary.llm.local_models as lm
import webmail_summary.llm.provider as prov
import webmail_summary.util.platform_caps as caps


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

def test_mlx_models_exist():
    assert len(lm.MLX_MODELS) >= 3
    for m in lm.MLX_MODELS:
        assert m.engine == "mlx"
        assert m.group == "mlx"


def test_gguf_models_exist():
    assert len(lm.GGUF_MODELS) >= 3
    for m in lm.GGUF_MODELS:
        assert m.engine == "gguf"


def test_counterpart_mapping():
    assert lm.get_counterpart_model_id("fast") == "mlx_fast"
    assert lm.get_counterpart_model_id("mlx_fast") == "fast"
    assert lm.get_counterpart_model_id("standard") == "mlx_standard"
    assert lm.get_counterpart_model_id("mlx_standard") == "standard"
    assert lm.get_counterpart_model_id("qwen35_4b") == "mlx_qwen35_4b"
    assert lm.get_counterpart_model_id("mlx_qwen35_4b") == "qwen35_4b"
    assert lm.get_counterpart_model_id("unknown") is None


def test_get_local_model_returns_mlx():
    m = lm.get_local_model("mlx_fast")
    assert m.id == "mlx_fast"
    assert m.engine == "mlx"


# ---------------------------------------------------------------------------
# Engine resolution
# ---------------------------------------------------------------------------

def test_resolve_engine_llamacpp(monkeypatch):
    class FakeSettings:
        local_engine = "llamacpp"
    assert prov._resolve_engine(FakeSettings()) == "llamacpp"


def test_resolve_engine_mlx_explicit(monkeypatch):
    class FakeSettings:
        local_engine = "mlx"
    assert prov._resolve_engine(FakeSettings()) == "mlx"


def test_resolve_engine_auto_non_apple(monkeypatch):
    monkeypatch.setattr(caps, "is_macos", lambda: False)
    monkeypatch.setattr(caps.platform, "machine", lambda: "x86_64")
    class FakeSettings:
        local_engine = "auto"
    assert prov._resolve_engine(FakeSettings()) == "llamacpp"


def test_resolve_engine_auto_apple_no_mlx(monkeypatch):
    monkeypatch.setattr(caps, "is_macos", lambda: True)
    monkeypatch.setattr(caps.platform, "machine", lambda: "arm64")
    # Patch find_mlx_installed to return None
    import webmail_summary.llm.mlx_engine as me
    monkeypatch.setattr(me, "_find_mlx_lm_python", lambda: None)
    class FakeSettings:
        local_engine = "auto"
    assert prov._resolve_engine(FakeSettings()) == "llamacpp"


# ---------------------------------------------------------------------------
# MLX status
# ---------------------------------------------------------------------------

def test_mlx_status_non_mlx_model():
    from webmail_summary.llm.mlx_status import check_mlx_ready

    result = check_mlx_ready(model_id="fast")
    # "fast" is a GGUF model, so model_cached should be False
    assert result.model_cached is False
