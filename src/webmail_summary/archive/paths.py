from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def _safe_seg(text: str, max_len: int = 80) -> str:
    text = text.strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = "default"
    if len(text) > max_len:
        text = text[:max_len]
    return text


@dataclass(frozen=True)
class MessagePaths:
    base_dir: Path

    @property
    def raw_eml(self) -> Path:
        return self.base_dir / "raw.eml"

    @property
    def body_html(self) -> Path:
        return self.base_dir / "body.html"

    @property
    def body_text(self) -> Path:
        return self.base_dir / "body.txt"

    @property
    def rendered_html(self) -> Path:
        return self.base_dir / "rendered.html"

    @property
    def attachments_dir(self) -> Path:
        return self.base_dir / "attachments"

    @property
    def external_dir(self) -> Path:
        return self.base_dir / "external"


def get_message_paths(
    *,
    data_root: Path,
    account_id: str,
    mailbox: str,
    uidvalidity: int,
    uid: int,
) -> MessagePaths:
    # data_root is typically %LOCALAPPDATA%\WebmailSummary
    acct = _safe_seg(account_id)
    mbox = _safe_seg(mailbox)
    base = data_root / "data" / "messages" / acct / mbox / str(uidvalidity) / str(uid)
    base.mkdir(parents=True, exist_ok=True)
    (base / "attachments").mkdir(parents=True, exist_ok=True)
    (base / "external").mkdir(parents=True, exist_ok=True)
    return MessagePaths(base_dir=base)
