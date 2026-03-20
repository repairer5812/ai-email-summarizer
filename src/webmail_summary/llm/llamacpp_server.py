from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import psutil

from webmail_summary.llm.base import LlmProvider, LlmResult
from webmail_summary.util.jsonish import coerce_summary_text, coerce_summary_value


@dataclass(frozen=True)
class LlamaCppServerConfig:
    server_exe: Path
    model_path: Path
    host: str = "127.0.0.1"
    port: int = 4891
    ctx_size: int = 4096
    max_tokens: int = 192
    request_timeout_s: float = 40.0
    max_attempts: int = 1
    total_request_budget_s: float = 45.0
    temperature: float = 0.2
    alias: str = "local"


_lock = threading.Lock()
_proc: subprocess.Popen[str] | None = None
_running_cfg: LlamaCppServerConfig | None = None
_idle_timer: threading.Timer | None = None
_IDLE_TIMEOUT_S = 600.0
_in_flight = 0


def _arm_idle_shutdown() -> None:
    global _idle_timer
    with _lock:
        if _in_flight > 0:
            return
    t = threading.Timer(_IDLE_TIMEOUT_S, stop_server)
    t.daemon = True
    with _lock:
        old = _idle_timer
        _idle_timer = t
    if old is not None:
        old.cancel()
    t.start()


def _base_url(cfg: LlamaCppServerConfig) -> str:
    return f"http://{cfg.host}:{int(cfg.port)}"


def _is_healthy(cfg: LlamaCppServerConfig) -> bool:
    try:
        r = requests.get(_base_url(cfg) + "/v1/models", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


def ensure_server(cfg: LlamaCppServerConfig) -> None:
    global _proc, _running_cfg

    # Kill any other llama-server instances bound to our port.
    # We want exactly one local server process so requests don't randomly
    # hit an older, heavier model.
    try:
        for c in psutil.net_connections(kind="tcp"):
            try:
                if not c.laddr or int(getattr(c.laddr, "port", 0)) != int(cfg.port):
                    continue
                if c.status != "LISTEN":
                    continue
                pid = int(c.pid or 0)
                if pid <= 0:
                    continue
                # Don't kill our own process if it's already running.
                if _proc is not None and _proc.poll() is None and pid == _proc.pid:
                    continue
                p = psutil.Process(pid)
                name = (p.name() or "").lower()
                if "llama-server" in name:
                    try:
                        p.terminate()
                    except Exception:
                        pass
            except Exception:
                continue

        # Give terminated processes a moment to exit.
        time.sleep(0.2)
    except Exception:
        pass

    with _lock:
        if _proc is not None and _running_cfg == cfg and _proc.poll() is None:
            if _is_healthy(cfg):
                _arm_idle_shutdown()
                return

        # If a different config is requested, stop the old server.
        if _proc is not None and _proc.poll() is None and _running_cfg != cfg:
            try:
                _proc.terminate()
            except Exception:
                pass
        _proc = None
        _running_cfg = None

        threads = max(1, min(8, (os.cpu_count() or 4)))
        cmd: list[str] = [
            str(cfg.server_exe),
            "--model",
            str(cfg.model_path),
            "--host",
            str(cfg.host),
            "--port",
            str(int(cfg.port)),
            "--ctx-size",
            str(int(cfg.ctx_size)),
            "-t",
            str(int(threads)),
            "--alias",
            str(cfg.alias),
            "--parallel",
            "1",
            "--cont-batching",
        ]

        # Use a quiet subprocess; server logs are not critical for the app.
        popen_kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
        }
        if os.name == "nt":
            # Prevent llama-server from opening a console window.
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        _proc = subprocess.Popen(
            cmd,
            **popen_kwargs,
        )
        _running_cfg = cfg

    # Wait outside lock for server to come up.
    start = time.time()
    while time.time() - start < 60:
        if _proc is not None and _proc.poll() is not None:
            raise RuntimeError("llama-server exited during startup")
        if _is_healthy(cfg):
            _arm_idle_shutdown()
            return
        time.sleep(0.25)

    raise RuntimeError("llama-server did not become ready")


def stop_server(*, force: bool = False) -> None:
    global _proc, _running_cfg, _idle_timer

    with _lock:
        if (not force) and _in_flight > 0:
            return
        proc = _proc
        _proc = None
        _running_cfg = None
        timer = _idle_timer
        _idle_timer = None

    if timer is not None:
        timer.cancel()

    if proc is None or proc.poll() is not None:
        return

    try:
        proc.terminate()
    except Exception:
        return

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)

    try:
        proc.kill()
    except Exception:
        pass


class LlamaCppServerProvider(LlmProvider):
    def __init__(self, cfg: LlamaCppServerConfig, tier: str = "standard") -> None:
        self._cfg = cfg
        self._tier = tier
        ensure_server(cfg)

    @property
    def tier(self) -> str:
        return self._tier

    def summarize(self, *, subject: str, body: str) -> LlmResult:
        ensure_server(self._cfg)
        started_at = time.monotonic()

        def _build_prompt(body_limit: int) -> str:
            b = str(body or "")[: max(0, int(body_limit))]
            parts: list[str] = [
                "You are an expert editor summarizing business communications.\n",
                "Return ONLY a single valid JSON object with keys: summary, tags (array of strings), backlinks (array of strings), personal (boolean).\n",
                "The summary MUST be a structural bullet list (JSON array of strings).\n",
                "**Crucial Rules**:\n",
                "1. Ignore all footer/technical noise: addresses, phone numbers, unsubscribe links, copyright, registration numbers, or technical part markers.\n",
                "2. Do NOT mention keywords like '정보통신망', '수신거부', '무단전재', '대표전화', '서울특별시'.\n",
                "3. Use bold grouping headers like **[Topic Name]** for related points.\n",
                "4. Ensure each group has at least 2 detailed points. Do not summarize to just one line.\n",
                "If you cannot output an array, output a single string using '; ' to separate bullet points (no newlines).\n",
            ]
            parts.append("Write summary, tags, and backlinks in Korean.\n")
            parts.extend(
                [
                    "Output must start with '{' and end with '}'. Do not use markdown or code fences.\n",
                    "Be concise. Tags should be short nouns. Backlinks should be topic names for Obsidian [[Topic/<name>]] pages (just the <name>).\n\n",
                    f"Subject: {subject}\n\n",
                    f"Body:\n{b}\n",
                ]
            )
            return "".join(parts)

        def _post(prompt: str) -> dict | None:
            global _in_flight
            body_len = len(str(body or ""))
            dynamic_max_tokens = int(self._cfg.max_tokens)
            if body_len <= 2500:
                dynamic_max_tokens = min(dynamic_max_tokens, 96)
            payload = {
                "model": self._cfg.alias,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(self._cfg.temperature),
                "max_tokens": int(dynamic_max_tokens),
                "stream": False,
            }

            with _lock:
                _in_flight += 1
                try:
                    if _idle_timer is not None:
                        _idle_timer.cancel()
                        # Keep reference; it will be replaced when re-armed.
                except Exception:
                    pass

            try:
                done = threading.Event()
                req_box: dict[str, requests.Response] = {}
                err_box: dict[str, Exception] = {}

                def _do_request() -> None:
                    try:
                        req_box["resp"] = requests.post(
                            _base_url(self._cfg) + "/v1/chat/completions",
                            json=payload,
                            timeout=(3.05, float(self._cfg.request_timeout_s)),
                        )
                    except Exception as ex:
                        err_box["err"] = ex
                    finally:
                        done.set()

                threading.Thread(target=_do_request, daemon=True).start()
                hard_wait_s = float(self._cfg.request_timeout_s) + 2.0
                if not done.wait(max(5.0, hard_wait_s)):
                    return {"__retry": "timeout"}
                if "err" in err_box:
                    raise err_box["err"]
                r = req_box.get("resp")
                if r is None:
                    return None
            finally:
                with _lock:
                    _in_flight = max(0, int(_in_flight) - 1)
                _arm_idle_shutdown()

            # Many llama-server errors return structured JSON. Handle context overflow
            # by retrying with a shorter body.
            if r.status_code >= 400:
                try:
                    err = r.json().get("error") or {}
                    msg = str(err.get("message") or "")
                    typ = str(err.get("type") or "")
                except Exception:
                    msg = ""
                    typ = ""

                if r.status_code == 400 and (
                    "exceed_context_size" in typ.lower()
                    or "exceeds the available context size" in msg.lower()
                ):
                    return {"__retry": "exceed_context"}

                return None

            try:
                return r.json()
            except Exception:
                return None

        data = None
        body_limit = 6000
        max_attempts = max(1, int(self._cfg.max_attempts))
        budget_s = max(10.0, float(self._cfg.total_request_budget_s))
        for _attempt in range(max_attempts):
            if (time.monotonic() - started_at) >= budget_s:
                return LlmResult(
                    summary="(LLM timeout)", tags=[], backlinks=[], personal=False
                )
            prompt = _build_prompt(body_limit)
            try:
                data = _post(prompt)
            except Exception:
                return LlmResult(
                    summary="(LLM unavailable)", tags=[], backlinks=[], personal=False
                )

            if isinstance(data, dict) and data.get("__retry") == "exceed_context":
                # Reduce body length and retry.
                if body_limit <= 800:
                    return LlmResult(
                        summary="(LLM unavailable)",
                        tags=[],
                        backlinks=[],
                        personal=False,
                    )
                body_limit = int(body_limit * 0.65)
                continue

            if isinstance(data, dict) and data.get("__retry") == "timeout":
                return LlmResult(
                    summary="(LLM timeout)",
                    tags=[],
                    backlinks=[],
                    personal=False,
                )

            break

        if not isinstance(data, dict):
            return LlmResult(
                summary="(LLM unavailable)", tags=[], backlinks=[], personal=False
            )

        def _extract_json(text: str) -> dict | None:
            dec = json.JSONDecoder()
            for m in re.finditer(r"\{", text):
                try:
                    obj, _end = dec.raw_decode(text[m.start() :])
                except Exception:
                    continue
                if isinstance(obj, dict):
                    return obj
            return None

        content = ""
        try:
            content = str(
                (((data.get("choices") or [])[0] or {}).get("message") or {}).get(
                    "content"
                )
                or ""
            )
        except Exception:
            content = ""

        content = content.strip()
        obj = None
        try:
            # Prefer strict JSON if possible.
            obj = json.loads(content)
        except Exception:
            obj = None

        if not isinstance(obj, dict):
            obj = _extract_json(content)
        if not isinstance(obj, dict):
            summary2 = coerce_summary_text(content)
            if any(
                x in summary2.lower()
                for x in [
                    "failed to format input",
                    "invalid codepoint",
                    "loading model",
                    "available commands",
                ]
            ):
                summary2 = "(LLM unavailable)"
            return LlmResult(
                summary=summary2 or "(no summary)",
                tags=[],
                backlinks=[],
                personal=False,
            )

        summary = coerce_summary_value(obj.get("summary"))
        raw_tags = obj.get("tags")
        raw_backlinks = obj.get("backlinks")
        tags = [
            str(x).strip() for x in (raw_tags if isinstance(raw_tags, list) else [])
        ]
        backlinks = [
            str(x).strip()
            for x in (raw_backlinks if isinstance(raw_backlinks, list) else [])
        ]
        tags = [t for t in tags if t]
        backlinks = [b for b in backlinks if b]
        personal = bool(obj.get("personal") or False)
        return LlmResult(
            summary=summary, tags=tags, backlinks=backlinks, personal=personal
        )
