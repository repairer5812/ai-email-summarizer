from __future__ import annotations

import email
import email.policy
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from typing import cast


@dataclass(frozen=True)
class ParsedEmail:
    subject: str
    from_addr: str
    date: str
    body_text: str


def _decode_maybe(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for fragment, enc in parts:
        if isinstance(fragment, bytes):
            out.append(fragment.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(fragment)
    return "".join(out)


def _html_to_text(html: str) -> str:
    # Minimal conversion without extra deps.
    # Keeps it simple for MVP; can be upgraded later.
    import re

    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _get_body_text(msg: Message) -> str:
    def _decode_part(part: Message) -> str:
        payload_any = part.get_payload(decode=True)
        charset = part.get_content_charset() or "utf-8"
        if isinstance(payload_any, (bytes, bytearray)):
            return bytes(payload_any).decode(charset, errors="replace").strip()
        if payload_any is None:
            return ""
        # Rare: payload could be a nested Message or list; keep a best-effort string.
        return str(payload_any).strip()

    if msg.is_multipart():
        # Prefer text/plain.
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if disp.startswith("attachment"):
                continue
            if ctype == "text/plain":
                return _decode_part(part)
        # Fallback to html.
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if disp.startswith("attachment"):
                continue
            if ctype == "text/html":
                return _html_to_text(_decode_part(part))
        return ""

    ctype = msg.get_content_type()
    if ctype == "text/plain":
        return _decode_part(msg)
    if ctype == "text/html":
        return _html_to_text(_decode_part(msg)).strip()
    return ""


def parse_rfc822(raw: bytes) -> ParsedEmail:
    msg = cast(Message, email.message_from_bytes(raw, policy=email.policy.default))
    subject = _decode_maybe(msg.get("Subject"))
    from_addr = _decode_maybe(msg.get("From"))
    date = _decode_maybe(msg.get("Date"))
    body_text = _get_body_text(msg)
    return ParsedEmail(
        subject=subject, from_addr=from_addr, date=date, body_text=body_text
    )
