from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from webmail_summary.llm.base import LlmProvider, LlmResult
from webmail_summary.util.jsonish import coerce_summary_text, coerce_summary_value


@dataclass(frozen=True)
class LlamaCppBinConfig:
    llama_cli_path: Path
    model_path: Path
    ctx_size: int = 4096
    max_tokens: int = 512
    temperature: float = 0.2


def _extract_json(text: str) -> dict | None:
    # Best-effort: find the first valid JSON object anywhere in the output.
    # Use raw_decode so braces inside strings don't break extraction.
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _end = dec.raw_decode(text[m.start() :])
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


class LlamaCppBinProvider(LlmProvider):
    def __init__(self, cfg: LlamaCppBinConfig, tier: str = "standard") -> None:
        self._cfg = cfg
        self._tier = tier

    @property
    def tier(self) -> str:
        return self._tier

    def summarize(self, *, subject: str, body: str) -> LlmResult:
        ko = True  # Default to Korean per PRD
        parts: list[str] = [
            "You are an expert editor summarizing business communications.\n",
            "Return ONLY a single valid JSON object with keys: summary, tags (array of strings), backlinks (array of strings), personal (boolean).\n",
            "The summary MUST be a structural bullet list (JSON array of strings).\n",
            "**Crucial Rules**:\n",
            "1. Ignore all footer/technical noise: addresses, phone numbers, unsubscribe links, copyright, or part markers.\n",
            "2. Do NOT mention keywords like '정보통신망', '수신거부', '무단전재'.\n",
            "3. Use bold grouping headers like **[Topic Name]** for related points.\n",
            "4. Ensure each group has at least 2 detailed points.\n",
            "If you cannot output an array, output a single string using '; ' to separate bullet points (no newlines).\n",
        ]
        parts.append("Write summary, tags, and backlinks in Korean.\n")
        parts.extend(
            [
                "Output must start with '{' and end with '}'. Do not use markdown or code fences.\n",
                "Be concise. Tags should be short nouns. Backlinks should be topic names for Obsidian [[Topic/<name>]] pages (just the <name>).\n\n",
                f"Subject: {subject}\n\n",
                f"Body:\n{body[:6000]}\n",
            ]
        )
        prompt = "".join(parts)

        threads = max(1, min(8, (os.cpu_count() or 4)))
        cmd = [
            str(self._cfg.llama_cli_path),
            "-m",
            str(self._cfg.model_path),
            "-p",
            prompt,
            "-n",
            str(int(self._cfg.max_tokens)),
            "--ctx-size",
            str(int(self._cfg.ctx_size)),
            "--temp",
            str(float(self._cfg.temperature)),
            "--threads",
            str(int(threads)),
            "--no-display-prompt",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
        except Exception:
            return LlmResult(
                summary="(LLM unavailable)", tags=[], backlinks=[], personal=False
            )

        out = (proc.stdout or "").strip()
        obj = _extract_json(out)
        if not obj:
            summary2 = coerce_summary_text(out)
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
