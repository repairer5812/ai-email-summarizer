from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SavedAttachment:
    filename: str
    rel_path: str
    mime_type: str | None
    size_bytes: int
    content_id: str | None
    is_inline: bool


def _sanitize_filename(name: str) -> str:
    name = name.strip().replace("\x00", "")
    name = os.path.basename(name)
    name = re.sub(r"[\\/:*?\"<>|]", "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "file.bin"


def _unique_path(dir_path: Path, filename: str) -> Path:
    p = dir_path / filename
    if not p.exists():
        return p
    stem = p.stem
    suf = p.suffix
    i = 1
    while True:
        cand = dir_path / f"{stem}_{i}{suf}"
        if not cand.exists():
            return cand
        i += 1


def extract_attachments(
    *, msg: Message, out_dir: Path
) -> tuple[list[SavedAttachment], dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[SavedAttachment] = []
    cid_map: dict[str, str] = {}

    counter = 1
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename() or ""
        content_id = (part.get("Content-ID") or "").strip().strip("<>")

        is_body = ctype in {"text/plain", "text/html"} and disp == "" and not filename
        if is_body:
            continue

        is_inline = disp == "inline" or bool(content_id)

        if not filename:
            ext = mimetypes.guess_extension(ctype) or ".bin"
            filename = f"part_{counter}{ext}"
            counter += 1
        filename = _sanitize_filename(filename)

        payload_any: Any = part.get_payload(decode=True)
        if isinstance(payload_any, (bytes, bytearray)):
            payload = bytes(payload_any)
        else:
            # Some malformed messages may return non-bytes payload; keep best-effort.
            payload = str(part.get_payload() or "").encode("utf-8", errors="replace")

        file_path = _unique_path(out_dir, filename)
        file_path.write_bytes(payload)

        rel = f"attachments/{file_path.name}"
        size = file_path.stat().st_size
        item = SavedAttachment(
            filename=file_path.name,
            rel_path=rel,
            mime_type=ctype,
            size_bytes=size,
            content_id=content_id or None,
            is_inline=is_inline,
        )
        saved.append(item)

        if content_id:
            cid_map[content_id] = rel

    return saved, cid_map
