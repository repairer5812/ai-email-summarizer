from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import cast

from webmail_summary.archive.html_rewrite import (
    ExternalAsset,
    rewrite_html_and_download_assets,
)
from webmail_summary.archive.html_sanitize import sanitize_html
from webmail_summary.archive.mime_parts import SavedAttachment, extract_attachments
from webmail_summary.archive.paths import MessagePaths
from webmail_summary.util.atomic_io import atomic_write_bytes, atomic_write_text


@dataclass(frozen=True)
class ArchiveResult:
    raw_eml_path: Path
    body_html_path: Path | None
    body_text_path: Path | None
    rendered_html_path: Path | None
    attachments: list[SavedAttachment]
    external_assets: list[ExternalAsset]


def _pick_body(msg: Message) -> tuple[str | None, str | None]:
    def decode_part(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if isinstance(payload, (bytes, bytearray)):
            charset = part.get_content_charset() or "utf-8"
            return bytes(payload).decode(charset, errors="replace")
        # Fallback
        return str(part.get_payload() or "")

    html: str | None = None
    text: str | None = None

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if html is None and part.get_content_type() == "text/html":
            html = decode_part(part)
        if text is None and part.get_content_type() == "text/plain":
            text = decode_part(part)
        if html is not None and text is not None:
            break

    return html, text


def archive_message(
    *,
    raw_rfc822: bytes,
    paths: MessagePaths,
    external_max_bytes: int,
) -> ArchiveResult:
    atomic_write_bytes(paths.raw_eml, raw_rfc822)
    msg = cast(Message, BytesParser(policy=policy.default).parsebytes(raw_rfc822))

    attachments, cid_map = extract_attachments(msg=msg, out_dir=paths.attachments_dir)

    html, text = _pick_body(msg)
    body_html_path = None
    body_text_path = None
    rendered_html_path = None
    external_assets: list[ExternalAsset] = []

    if text is not None:
        body_text_path = paths.body_text
        atomic_write_text(body_text_path, text)

    if html is not None:
        body_html_path = paths.body_html
        atomic_write_text(body_html_path, html)
        rewritten, external_assets = rewrite_html_and_download_assets(
            html=html,
            external_dir=paths.external_dir,
            cid_map=cid_map,
            max_total_bytes=external_max_bytes,
        )
        sanitized = sanitize_html(rewritten)
        rendered_html_path = paths.rendered_html
        atomic_write_text(rendered_html_path, sanitized)

    return ArchiveResult(
        raw_eml_path=paths.raw_eml,
        body_html_path=body_html_path,
        body_text_path=body_text_path,
        rendered_html_path=rendered_html_path,
        attachments=attachments,
        external_assets=external_assets,
    )
