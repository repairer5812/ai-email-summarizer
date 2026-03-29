from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
from webmail_summary.util.jsonish import (
    coerce_summary_text,
    coerce_summary_value,
    extract_first_json_object,
)


@dataclass(frozen=True)
class CloudConfig:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"


class CloudProvider(LlmProvider):
    def __init__(self, cfg: CloudConfig) -> None:
        self._cfg = cfg

    @property
    def tier(self) -> str:
        return "cloud"

    def supports_multimodal_inputs(self) -> bool:
        return self._supports_multimodal()

    def _supports_multimodal(self) -> bool:
        base = str(self._cfg.base_url or "").lower()
        model = str(self._cfg.model or "").lower()
        if "generativelanguage.googleapis.com" in base:
            return True
        allow = [
            "gpt-4o",
            "gpt-4.1",
            "gemini",
            "claude-3",
            "claude-4",
            "qwen2.5-vl",
            "qwen-vl",
            "llama-3.2-vision",
            "pixtral",
        ]
        return any(x in model for x in allow)

    def _build_image_parts(
        self, multimodal_inputs: list[LlmImageInput] | None
    ) -> list[dict]:
        if not multimodal_inputs or not self._supports_multimodal():
            return []

        parts: list[dict] = []
        for item in multimodal_inputs:
            try:
                p = Path(str(item.path or "")).resolve()
                if not p.is_file():
                    continue
                blob = p.read_bytes()
                if not blob:
                    continue
                mime = (
                    str(item.mime_type or "").strip()
                    or mimetypes.guess_type(p.name)[0]
                    or "image/jpeg"
                )
                b64 = base64.b64encode(blob).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                            "detail": str(item.detail or "auto"),
                        },
                    }
                )
            except Exception:
                continue
        return parts

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
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
            "Output must start with '{' and end with '}'. Do not wrap output in markdown/code fences.\n",
            "Write everything in Korean.\n\n",
        ]
        parts.extend([f"Subject: {subject}\n\n", f"Body:\n{body[:12000]}\n"])
        prompt = "".join(parts)

        # Handle Google Gemini Native API
        if "generativelanguage.googleapis.com" in self._cfg.base_url:
            return self._summarize_gemini(prompt, multimodal_inputs=multimodal_inputs)

        url = f"{self._cfg.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        # Add headers for specific providers
        if "openrouter.ai" in self._cfg.base_url:
            headers["X-Title"] = "WebmailSummary"
        if "api.anthropic.com" in self._cfg.base_url:
            headers["anthropic-version"] = "2023-06-01"

        image_parts = self._build_image_parts(multimodal_inputs)
        user_content: str | list[dict]
        if image_parts:
            user_content = [{"type": "text", "text": prompt}, *image_parts]
        else:
            user_content = prompt

        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
        }

        try:
            r = self._post_with_adaptive_retry(
                url=url,
                headers=headers,
                payload=payload,
                max_attempts=3,
                initial_backoff_s=0.5,
                max_backoff_s=6.0,
            )
            if r.status_code != 200:
                return LlmResult(
                    summary=f"(LLM error: {r.status_code} {r.text[:100]})",
                    tags=[],
                    backlinks=[],
                    personal=False,
                )
            data = r.json()
            text = (
                (((data.get("choices") or [])[0] or {}).get("message") or {}).get(
                    "content"
                )
                or ""
            ).strip()
        except Exception as e:
            return LlmResult(
                summary=f"(LLM unavailable: {str(e)})",
                tags=[],
                backlinks=[],
                personal=False,
            )

        return self._parse_result(text)

    def _retry_after_seconds(self, header_value: str | None) -> float | None:
        if not header_value:
            return None
        raw = str(header_value).strip()
        if not raw:
            return None

        try:
            sec = float(raw)
            if sec >= 0:
                return sec
        except Exception:
            pass

        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            wait_s = (dt - now).total_seconds()
            if wait_s > 0:
                return wait_s
        except Exception:
            pass
        return None

    def _post_with_adaptive_retry(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict,
        max_attempts: int,
        initial_backoff_s: float,
        max_backoff_s: float,
    ) -> requests.Response:
        last_resp: requests.Response | None = None
        for attempt in range(max(1, int(max_attempts))):
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            last_resp = r
            if r.status_code != 429:
                return r

            if attempt >= max_attempts - 1:
                return r

            retry_after = self._retry_after_seconds(r.headers.get("Retry-After"))
            if retry_after is None:
                retry_after = min(max_backoff_s, initial_backoff_s * (2**attempt))
            time.sleep(max(0.0, float(retry_after)))

        if last_resp is None:
            raise RuntimeError("request failed before receiving a response")
        return last_resp

    def _summarize_gemini(
        self,
        prompt: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        model_id = self._cfg.model
        if not model_id.startswith("models/"):
            model_id = f"models/{model_id}"

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_id}:generateContent?key={self._cfg.api_key}"
        gemini_parts: list[dict] = [{"text": prompt}]
        for item in multimodal_inputs or []:
            try:
                p = Path(str(item.path or "")).resolve()
                if not p.is_file():
                    continue
                blob = p.read_bytes()
                if not blob:
                    continue
                mime = (
                    str(item.mime_type or "").strip()
                    or mimetypes.guess_type(p.name)[0]
                    or "image/jpeg"
                )
                gemini_parts.append(
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(blob).decode("ascii"),
                        }
                    }
                )
            except Exception:
                continue
        payload = {
            "contents": [{"parts": gemini_parts}],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        }

        # Handle 429 Resource Exhausted with retry
        last_status = 0
        last_resp = ""
        import time

        for attempt in range(3):
            try:
                r = requests.post(url, json=payload, timeout=120)
                last_status = r.status_code
                last_resp = r.text

                if r.status_code == 429:
                    # If the error message explicitly says limit is 0, don't bother retrying
                    if '"limit": 0' in last_resp or '"limit":0' in last_resp:
                        return LlmResult(
                            summary=f"(Gemini Quota Error: Daily limit is 0 for this key. Please check Google AI Studio: {last_resp[:100]})",
                            tags=[],
                            backlinks=[],
                            personal=False,
                        )
                    time.sleep(2 * (attempt + 1))
                    continue

                if r.status_code != 200:
                    return LlmResult(
                        summary=f"(Gemini error {r.status_code}: {last_resp[:200]})",
                        tags=[],
                        backlinks=[],
                        personal=False,
                    )
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return self._parse_result(text)
            except Exception as e:
                last_resp = str(e)
                time.sleep(1)

        return LlmResult(
            summary=f"(Gemini failed after retries. Last status {last_status}: {last_resp[:200]})",
            tags=[],
            backlinks=[],
            personal=False,
        )

    def _parse_result(self, text: str) -> LlmResult:
        obj = None
        try:
            obj = json.loads(text)
        except Exception:
            obj = extract_first_json_object(text)

        if isinstance(obj, dict):
            summary = coerce_summary_value(obj.get("summary"))
            tags = [str(x).strip() for x in (obj.get("tags") or []) if str(x).strip()]
            backlinks = [
                str(x).strip() for x in (obj.get("backlinks") or []) if str(x).strip()
            ]
            personal = bool(obj.get("personal") or False)
            return LlmResult(
                summary=summary, tags=tags, backlinks=backlinks, personal=personal
            )

        summary2 = coerce_summary_text(text)
        return LlmResult(
            summary=summary2 or "(no summary)", tags=[], backlinks=[], personal=False
        )
