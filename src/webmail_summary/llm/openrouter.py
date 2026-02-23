from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from webmail_summary.llm.base import LlmProvider, LlmResult
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

    def summarize(self, *, subject: str, body: str) -> LlmResult:
        parts: list[str] = [
            "You are an expert editor summarizing business communications.\n",
            "Return ONLY a single valid JSON object with keys: summary, tags (array of strings), backlinks (array of strings), personal (boolean).\n",
            "The summary MUST be a structural bullet list (JSON array of strings).\n",
            "**Crucial Rules**:\n",
            "1. Ignore all footer/technical noise: addresses, phone numbers, unsubscribe links, copyright, registration numbers, or technical part markers.\n",
            "2. Do NOT mention keywords like '정보통신망', '수신거부', '무단전재', '대표전화', '서울특별시'.\n",
            "3. Use bold grouping headers like **[Topic Name]** for related points.\n",
            "4. Ensure each group has at least 2 detailed points.\n",
            "Write everything in Korean.\n\n",
        ]
        parts.extend([f"Subject: {subject}\n\n", f"Body:\n{body[:12000]}\n"])
        prompt = "".join(parts)

        # Handle Google Gemini Native API
        if "generativelanguage.googleapis.com" in self._cfg.base_url:
            return self._summarize_gemini(prompt)

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

        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120)
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

    def _summarize_gemini(self, prompt: str) -> LlmResult:
        model_id = self._cfg.model
        if not model_id.startswith("models/"):
            model_id = f"models/{model_id}"

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_id}:generateContent?key={self._cfg.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
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
