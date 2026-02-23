from __future__ import annotations

import json
import re


def extract_first_json_object(text: str) -> dict | None:
    """Best-effort: find and parse the first JSON object in free-form text."""

    s = str(text or "")
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", s):
        try:
            obj, _end = dec.raw_decode(s[m.start() :])
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def extract_json_string_value(text: str, key: str) -> str | None:
    """Extract a JSON string value for a key from a JSON-ish blob.

    This works even when the overall JSON is truncated, as long as the
    target string literal is intact.
    """

    s = str(text or "")
    k = str(key)
    i = s.find(f'"{k}"')
    if i < 0:
        return None

    # Find the ':' after the key.
    j = s.find(":", i)
    if j < 0:
        return None
    # Find the opening quote for the string.
    q = s.find('"', j)
    if q < 0:
        return None

    # Scan to the closing quote, respecting escapes.
    esc = False
    end = -1
    for pos in range(q + 1, len(s)):
        ch = s[pos]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            end = pos
            break
    if end < 0:
        return None

    lit = s[q : end + 1]
    try:
        v = json.loads(lit)
    except Exception:
        return None
    return v if isinstance(v, str) else None


def coerce_summary_text(text: str) -> str:
    """Turn JSON/JSON-ish model output into a displayable summary string."""

    s = (text or "").strip()
    if not s:
        return ""

    obj = extract_first_json_object(s)
    if isinstance(obj, dict):
        v = obj.get("summary")
        if isinstance(v, str) and v.strip():
            return v.strip()

    v2 = extract_json_string_value(s, "summary")
    if isinstance(v2, str) and v2.strip():
        return v2.strip()

    # Strip common code fence wrapper if present.
    if s.startswith("```"):
        s2 = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s2 = re.sub(r"\s*```\s*$", "", s2)
        s2 = s2.strip()
        if s2 and s2 != s:
            return coerce_summary_text(s2)

    return s


def coerce_summary_value(v: object) -> str:
    """Normalize summary field (string or list) to display text."""

    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        parts: list[str] = []
        for x in v:
            if not isinstance(x, str):
                continue
            t = x.strip()
            if not t:
                continue
            if t.startswith("-"):
                parts.append(t)
            else:
                parts.append("- " + t)
        return "\n".join(parts).strip()
    # Fallback
    try:
        return str(v).strip()
    except Exception:
        return ""
