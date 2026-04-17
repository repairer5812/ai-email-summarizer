"""MLX-LM server provider for Apple Silicon Macs.

Mirrors the LlamaCppServerProvider pattern but spawns ``mlx_lm.server``
instead of ``llama-server``.  The API is OpenAI-compatible
(``/v1/chat/completions``), so the HTTP call logic is shared.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass

import requests

from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
from webmail_summary.llm.mlx_engine import MlxInstall
from webmail_summary.util.jsonish import coerce_summary_text, coerce_summary_value

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MlxServerConfig:
    mlx_install: MlxInstall
    hf_repo_id: str
    host: str = "127.0.0.1"
    port: int = 4892
    max_tokens: int = 384
    request_timeout_s: float = 120.0
    total_request_budget_s: float = 180.0
    temperature: float = 0.2


# ---------------------------------------------------------------------------
# Process management  (global singleton — one mlx server at a time)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_proc: subprocess.Popen[str] | None = None
_running_cfg: MlxServerConfig | None = None
_idle_timer: threading.Timer | None = None
_IDLE_TIMEOUT_S = 600.0
_in_flight = 0


def _arm_idle_shutdown() -> None:
    global _idle_timer
    with _lock:
        if _in_flight > 0:
            return
    t = threading.Timer(_IDLE_TIMEOUT_S, stop_mlx_server)
    t.daemon = True
    with _lock:
        old = _idle_timer
        _idle_timer = t
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t.start()


def stop_mlx_server() -> None:
    global _proc, _running_cfg, _idle_timer
    with _lock:
        p = _proc
        _proc = None
        _running_cfg = None
        t = _idle_timer
        _idle_timer = None
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    if p and p.poll() is None:
        log.info("Stopping mlx_lm.server (pid %s)", p.pid)
        try:
            p.terminate()
            p.wait(timeout=10)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _health_check(cfg: MlxServerConfig, timeout: float = 3.0) -> bool:
    try:
        r = requests.get(
            f"http://{cfg.host}:{cfg.port}/v1/models",
            timeout=timeout,
        )
        return r.status_code == 200
    except Exception:
        return False


def ensure_mlx_server(cfg: MlxServerConfig) -> None:
    """Start the MLX server if not already running with the same config."""
    global _proc, _running_cfg

    with _lock:
        if _proc and _proc.poll() is None and _running_cfg == cfg:
            if _health_check(cfg):
                return

    # Stop any existing server.
    stop_mlx_server()

    cmd = [
        *cfg.mlx_install.server_cmd,
        "--model", cfg.hf_repo_id,
        "--host", cfg.host,
        "--port", str(cfg.port),
    ]
    log.info("Starting mlx_lm.server: %s", " ".join(cmd))

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    # Wait for server to become ready (model download + load can take time).
    deadline = time.monotonic() + 300  # 5 min for first-time model download
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = ""
            if proc.stdout:
                out = proc.stdout.read()[:2000]
            raise RuntimeError(f"mlx_lm.server exited (rc={proc.returncode}): {out}")
        if _health_check(cfg, timeout=2.0):
            break
        time.sleep(2.0)
    else:
        proc.terminate()
        raise RuntimeError("mlx_lm.server did not become healthy within 5 minutes")

    with _lock:
        _proc = proc
        _running_cfg = cfg
    log.info("mlx_lm.server ready on port %s (pid %s)", cfg.port, proc.pid)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class MlxServerProvider(LlmProvider):
    def __init__(self, cfg: MlxServerConfig, tier: str = "standard") -> None:
        self._cfg = cfg
        self._tier = tier

    @property
    def tier(self) -> str:
        return self._tier

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        ensure_mlx_server(self._cfg)

        def _build_prompt(body_limit: int) -> str:
            b = str(body or "")[: max(0, int(body_limit))]
            parts: list[str] = [
                "You are an expert editor summarizing business communications.\n",
                "Return ONLY a single valid JSON object with keys: summary, tags (array of strings), backlinks (array of strings), personal (boolean).\n",
                "The summary MUST be a JSON array of strings where each item is one bullet point.\n",
                "Write 8~12 bullet points total (at least 6 if the email is very short).\n",
                "Put the most important points first. Do not repeat the same idea across bullets.\n",
                "**Crucial Rules**:\n",
                "1. Ignore all footer/technical noise: addresses, phone numbers, unsubscribe links, copyright, registration numbers, or technical part markers.\n",
                "2. Do NOT mention keywords like '정보통신망', '수신거부', '무단전재', '대표전화', '서울특별시'.\n",
                "3. Do not output a 1-line summary. Always produce multiple bullets.\n",
                "4. Prefer concrete facts (who/what/why/impact). Avoid generic filler.\n",
                "5. Prefer bullets in '주체: 내용' format when possible (e.g., '회사명: 무엇을 했는지').\n",
                "If you cannot output an array, output a single string using '; ' to separate bullet points (no newlines).\n",
                "Write summary, tags, and backlinks in Korean.\n",
                "Output must start with '{' and end with '}'. Do not wrap output in markdown/code fences.\n",
                "Keep each bullet concise, but DO NOT reduce the number of bullets. Tags should be short nouns. Backlinks should be topic names for Obsidian [[Topic/<name>]] pages (just the <name>).\n\n",
                f"Subject: {subject}\n\n",
                f"Body:\n{b}\n",
            ]
            return "".join(parts)

        def _post(prompt: str) -> dict | None:
            global _in_flight
            payload = {
                "model": self._cfg.hf_repo_id,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(self._cfg.temperature),
                "max_tokens": int(self._cfg.max_tokens),
                "stream": False,
            }

            with _lock:
                _in_flight += 1
                try:
                    if _idle_timer is not None:
                        _idle_timer.cancel()
                except Exception:
                    pass

            try:
                url = f"http://{self._cfg.host}:{self._cfg.port}/v1/chat/completions"
                r = requests.post(
                    url,
                    json=payload,
                    timeout=self._cfg.request_timeout_s,
                )
                if r.status_code >= 400:
                    log.warning("MLX server returned %s: %s", r.status_code, r.text[:300])
                    return None
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    return None
                text = choices[0].get("message", {}).get("content", "")
                return _parse_response(text)
            except requests.Timeout:
                log.warning("MLX request timed out after %ss", self._cfg.request_timeout_s)
                return None
            except Exception as e:
                log.warning("MLX request failed: %s", e)
                return None
            finally:
                with _lock:
                    _in_flight -= 1
                _arm_idle_shutdown()

        # Try with full body, then reduce on failure.
        for limit in [6000, 3000, 1500]:
            prompt = _build_prompt(limit)
            result = _post(prompt)
            if result:
                return LlmResult(
                    summary=result.get("summary", ""),
                    tags=result.get("tags", []),
                    backlinks=result.get("backlinks", []),
                    personal=bool(result.get("personal", False)),
                )

        return LlmResult(
            summary="(MLX 요약 실패)",
            tags=[],
            backlinks=[],
            personal=False,
        )


def _parse_response(text: str) -> dict | None:
    """Parse LLM response text into a dict with summary/tags/backlinks/personal."""
    text = (text or "").strip()
    if not text:
        return None

    # Try direct JSON parse.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            summary = coerce_summary_value(obj.get("summary"))
            return {
                "summary": summary,
                "tags": [str(t).strip() for t in (obj.get("tags") or []) if str(t).strip()],
                "backlinks": [str(b).strip() for b in (obj.get("backlinks") or []) if str(b).strip()],
                "personal": bool(obj.get("personal", False)),
            }
    except json.JSONDecodeError:
        pass

    # Try extracting first JSON object from text.
    try:
        from webmail_summary.util.jsonish import extract_first_json_object

        obj = extract_first_json_object(text)
        if obj and isinstance(obj, dict):
            summary = coerce_summary_value(obj.get("summary"))
            return {
                "summary": summary,
                "tags": [str(t).strip() for t in (obj.get("tags") or []) if str(t).strip()],
                "backlinks": [str(b).strip() for b in (obj.get("backlinks") or []) if str(b).strip()],
                "personal": bool(obj.get("personal", False)),
            }
    except Exception:
        pass

    # Fallback: treat entire text as summary.
    return {
        "summary": coerce_summary_text(text),
        "tags": [],
        "backlinks": [],
        "personal": False,
    }
