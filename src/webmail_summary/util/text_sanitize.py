from __future__ import annotations


def sanitize_text_for_llm(text: str) -> str:
    """Make text safe for LLM backends (llama.cpp/OpenRouter).

    This removes NUL bytes and replaces invalid Unicode code points
    (e.g. lone surrogates) with the replacement character.
    """

    s = str(text or "")
    if "\x00" in s:
        s = s.replace("\x00", " ")
    # Force a valid UTF-8 roundtrip to eliminate lone surrogates.
    try:
        s = s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        # Worst case: return a best-effort ASCII-ish string.
        s = "".join((ch if ord(ch) < 128 else "?") for ch in s)
    return s
