"""One predicate for summaries that failed and should be retried or omitted."""

from __future__ import annotations

import re

# Strings the sync and resummarize paths store when the model call fails.
# ``is_failed_summary`` matches these, so a new fallback has to be added here
# or the day view will treat it as a real summary.
SUMMARY_LLM_TIMEOUT = "(LLM timeout)"
SUMMARY_LLM_UNAVAILABLE = "(LLM unavailable)"
SUMMARY_LLM_CALL_FAILED = "(LLM 호출 실패)"
SUMMARY_LLM_RESPONSE_TIMEOUT = "(LLM 응답 timeout)"
SUMMARY_LLM_NETWORK = "(LLM 네트워크 오류)"
SUMMARY_LLM_HTTP = "(LLM HTTP 오류)"
SUMMARY_LLM_PARSE = "(LLM 응답 파싱 실패)"
SUMMARY_LLM_CANCELLED = "(LLM cancelled)"

PRODUCED_FAILURE_SUMMARIES = (
    SUMMARY_LLM_TIMEOUT,
    SUMMARY_LLM_UNAVAILABLE,
    SUMMARY_LLM_CALL_FAILED,
    SUMMARY_LLM_RESPONSE_TIMEOUT,
    SUMMARY_LLM_NETWORK,
    SUMMARY_LLM_HTTP,
    SUMMARY_LLM_PARSE,
    SUMMARY_LLM_CANCELLED,
)

# Substrings of the lowered summary. "llm timeout" also matches the
# unparenthesized form the resummarize check has always accepted.
_TEXT_MARKERS = tuple(item.lower() for item in PRODUCED_FAILURE_SUMMARIES) + (
    "llm timeout",
    "llm unavailable",
    "llm error",
    "failed to format input",
    "invalid codepoint",
    "loading model",
    "available commands",
)

# Older builds stored these mojibake tokens. The previous compact-string
# search dropped ASCII "?", so the tokens never matched. Match the raw text.
_BROKEN_LITERALS = (
    "?\ubdbf\ube5f?\ub181\uc4ec",
    "?\uacf8\uaf6d?\ubdbf\ube5f??\u3049?\ub300?\u8b70\uae4a\ube40?\ub348\ub58e",
)


def is_failed_summary(summary: str) -> bool:
    """Return True when ``summary`` is empty, a fallback, or not a real digest.

    Used by the resummarize badge, the daily overview input filter, and the
    home/day views. A hit means the mail should be retried and must not be
    fed into the day-level model.
    """
    s = re.sub(r"\s+", " ", (summary or "").strip()).lower()
    if not s:
        return True
    if any(token in s for token in _BROKEN_LITERALS):
        return True
    compact = "".join(ch for ch in s if ch.isalnum() or ("\uac00" <= ch <= "\ud7a3"))
    if "nosummary" in compact or "요약없음" in compact:
        return True
    if "요약항목이부족합니다" in compact:
        return True
    if any(marker in s for marker in _TEXT_MARKERS):
        return True
    if s.startswith("{") or s.startswith("```"):
        return True
    return False
