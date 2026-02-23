from __future__ import annotations

import re


def safe_filename(text: str, *, max_len: int = 120) -> str:
    text = (text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", "-", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "(no subject)"
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def safe_topic_name(text: str, *, max_len: int = 80) -> str:
    text = (text or "").strip().strip("[]")
    text = re.sub(r"[\\/:*?\"<>|]", "-", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "Topic"
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text
