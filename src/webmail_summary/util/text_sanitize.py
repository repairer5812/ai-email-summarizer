from __future__ import annotations

import re


_HARD_REPLY_SPLIT_PATTERNS = [
    re.compile(r"^\s*[-_]{2,}\s*Original Message\s*[-_]{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*On\s+.+\s+wrote:\s*$", re.IGNORECASE),
]

_HEADER_BLOCK_PATTERNS = [
    re.compile(r"^\s*(From|Sent|To|Subject):\s*.+$", re.IGNORECASE),
    re.compile(r"^\s*(보낸사람|보낸 사람|보낸날짜|수신|참조|제목)\s*:\s*.+$"),
]


def html_to_visible_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(str(html or ""), "html.parser")
    for tag in soup(["script", "style", "noscript", "head", "title", "meta"]):
        tag.decompose()
    for node in soup.select(
        "blockquote, .gmail_quote, .protonmail_quote, .yahoo_quoted, "
        "[style*='display:none'], [style*='display: none'], "
        "[style*='visibility:hidden'], [style*='visibility: hidden']"
    ):
        node.decompose()
    return soup.get_text("\n")


def prepare_body_for_llm(body: str, *, max_chars: int = 7000) -> str:
    s = str(body or "")
    if not s:
        return s

    lines = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    clipped: list[str] = []
    has_meaningful_content = False
    for line in lines:
        if any(p.match(line) for p in _HARD_REPLY_SPLIT_PATTERNS):
            # Once we already captured real content, this marks quoted history.
            if has_meaningful_content:
                break
            # If this marker appears at the top, skip it and continue to salvage
            # the forwarded content that follows.
            continue

        if any(p.match(line) for p in _HEADER_BLOCK_PATTERNS):
            # Forwarded messages often begin with header blocks.
            # At top: skip header lines; after content starts: treat as quote boundary.
            if has_meaningful_content:
                break
            continue

        if line.strip():
            has_meaningful_content = True
        clipped.append(line)

    s = "\n".join(clipped).strip()

    # Guardrail: if aggressive header stripping made the text empty,
    # fall back to non-header lines from the original body.
    if not s:
        rescued: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            if any(p.match(line) for p in _HEADER_BLOCK_PATTERNS):
                continue
            if any(p.match(line) for p in _HARD_REPLY_SPLIT_PATTERNS):
                continue
            rescued.append(line)
        s = "\n".join(rescued).strip()

    if not s:
        return ""

    # Regular whitespace normalization/clipping.
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)

    lim = max(500, int(max_chars))
    if len(s) > lim:
        s = s[:lim]
    return s


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
