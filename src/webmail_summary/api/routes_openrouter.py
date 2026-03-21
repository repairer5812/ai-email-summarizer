from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import keyring
import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from webmail_summary.util.app_data import get_app_data_dir


router = APIRouter(prefix="/api")


@dataclass(frozen=True)
class OpenRouterModel:
    id: str
    name: str
    context_length: int
    prompt_price: str
    completion_price: str
    is_free_variant: bool

    @property
    def label(self) -> str:
        parts: list[str] = [self.id]
        if self.name and self.name.strip() and self.name.strip() != self.id:
            parts.append(self.name.strip())

        meta: list[str] = []
        if self.context_length > 0:
            meta.append(f"ctx {self.context_length}")
        if self.is_free_variant:
            meta.append("free")
        if meta:
            parts.append("(" + ", ".join(meta) + ")")
        return " - ".join([p for p in parts if p])


_CACHE_TTL_S = 6 * 60 * 60
_cache: dict[str, object] = {
    "fetched_at": 0.0,
    "models": [],
}


def _cache_path() -> Path:
    d = get_app_data_dir() / "runtime"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d / "openrouter_models_cache.json"


def _load_cache_file() -> list[OpenRouterModel] | None:
    p = _cache_path()
    try:
        raw = p.read_text(encoding="utf-8")
        obj = json.loads(raw)
        items = obj.get("models") if isinstance(obj, dict) else None
        if not isinstance(items, list):
            return None
        out: list[OpenRouterModel] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            mid = str(x.get("id") or "").strip()
            if not mid:
                continue
            out.append(
                OpenRouterModel(
                    id=mid,
                    name=str(x.get("name") or "").strip(),
                    context_length=int(float(x.get("context_length") or 0)),
                    prompt_price=str(x.get("prompt_price") or "").strip(),
                    completion_price=str(x.get("completion_price") or "").strip(),
                    is_free_variant=bool(x.get("is_free_variant") or False),
                )
            )
        return out
    except Exception:
        return None


def _write_cache_file(models: list[OpenRouterModel]) -> None:
    p = _cache_path()
    try:
        payload = {
            "updated_at": time.time(),
            "models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "context_length": int(m.context_length),
                    "prompt_price": m.prompt_price,
                    "completion_price": m.completion_price,
                    "is_free_variant": bool(m.is_free_variant),
                }
                for m in models
            ],
        }
        tmp = p.with_name(p.name + f".tmp.{int(time.time())}")
        tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        try:
            tmp.replace(p)
        except Exception:
            try:
                p.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        return


def _is_free_variant(model_id: str) -> bool:
    return str(model_id).strip().lower().endswith(":free")


def _fetch_openrouter_models(*, api_key: str) -> list[OpenRouterModel]:
    url = "https://openrouter.ai/api/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter models HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("OpenRouter models response missing data[]")

    out: list[OpenRouterModel] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = str(it.get("id") or "").strip()
        if not mid:
            continue
        name = str(it.get("name") or "").strip()
        ctx = 0
        try:
            ctx = int(float(it.get("context_length") or 0))
        except Exception:
            ctx = 0

        pricing = it.get("pricing") if isinstance(it.get("pricing"), dict) else {}
        prompt_price = str((pricing or {}).get("prompt") or "").strip()
        completion_price = str((pricing or {}).get("completion") or "").strip()
        out.append(
            OpenRouterModel(
                id=mid,
                name=name,
                context_length=ctx,
                prompt_price=prompt_price,
                completion_price=completion_price,
                is_free_variant=_is_free_variant(mid),
            )
        )

    out.sort(key=lambda m: (0 if m.is_free_variant else 1, m.id.lower()))
    return out


def _get_models_cached(*, force_refresh: bool) -> tuple[list[OpenRouterModel], bool]:
    now = time.time()
    fetched_at_raw = _cache.get("fetched_at")
    fetched_at = 0.0
    if isinstance(fetched_at_raw, (int, float)):
        fetched_at = float(fetched_at_raw)
    if not force_refresh and (now - fetched_at) < _CACHE_TTL_S:
        models = _cache.get("models")
        if (
            isinstance(models, list)
            and models
            and isinstance(models[0], OpenRouterModel)
        ):
            return models, False

    api_key = ""
    try:
        api_key = keyring.get_password("webmail-summary::openrouter", "api_key") or ""
    except Exception:
        api_key = ""
    if not api_key.strip():
        cached_file = _load_cache_file()
        if cached_file:
            return cached_file, False
        raise RuntimeError("OpenRouter API key not set in setup")

    try:
        models2 = _fetch_openrouter_models(api_key=api_key.strip())
    except Exception:
        cached_file = _load_cache_file()
        if cached_file:
            return cached_file, False
        models_mem = _cache.get("models")
        if (
            isinstance(models_mem, list)
            and models_mem
            and isinstance(models_mem[0], OpenRouterModel)
        ):
            return models_mem, False
        raise

    _cache["fetched_at"] = now
    _cache["models"] = models2
    _write_cache_file(models2)
    return models2, True


@router.get("/openrouter/models")
def openrouter_models(refresh: int = 0, q: str = "", limit: int = 500):
    try:
        models, refreshed = _get_models_cached(force_refresh=bool(int(refresh or 0)))
    except Exception as e:
        return JSONResponse(
            {
                "error": "openrouter_models_unavailable",
                "message": str(e),
            },
            status_code=409,
        )

    query = str(q or "").strip().lower()
    if query:
        models = [
            m
            for m in models
            if query in m.id.lower() or (m.name and query in m.name.lower())
        ]

    try:
        lim = max(1, min(2000, int(limit)))
    except Exception:
        lim = 500
    models = models[:lim]

    return {
        "refreshed": bool(refreshed),
        "count": len(models),
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "label": m.label,
                "context_length": int(m.context_length),
                "prompt_price": m.prompt_price,
                "completion_price": m.completion_price,
                "is_free_variant": bool(m.is_free_variant),
            }
            for m in models
        ],
    }
