from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MdDoc:
    title: str
    date: dt.date
    sender: str
    subject: str
    summary: str
    tags: list[str]
    backlinks: list[str]
    body_excerpt: str
    source_uid: int


def _slug_filename(text: str, max_len: int = 120) -> str:
    # Windows-friendly filename
    text = re.sub(r"[\\/:*?\"<>|]", "-", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "(no subject)"
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def write_obsidian_markdown(vault_path: Path, subdir: str, doc: MdDoc) -> Path:
    out_dir = vault_path / subdir / f"{doc.date:%Y-%m}"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{doc.date:%Y-%m-%d} - {_slug_filename(doc.subject)}.md"
    out_path = out_dir / filename

    tags = [t.strip().lstrip("#") for t in doc.tags if t.strip()]
    backlinks = [b.strip().strip("[]") for b in doc.backlinks if b.strip()]

    frontmatter_lines = [
        "---",
        f"title: {doc.title}",
        f"date: {doc.date:%Y-%m-%d}",
        f"sender: {doc.sender}",
        f"subject: {doc.subject}",
        f"source_uid: {doc.source_uid}",
        "tags:",
    ]
    for t in tags:
        frontmatter_lines.append(f"  - {t}")
    frontmatter_lines.append("backlinks:")
    for b in backlinks:
        frontmatter_lines.append(f"  - {b}")
    frontmatter_lines.append("---")

    backlink_line = " ".join([f"[[{b}]]" for b in backlinks])

    content = "\n".join(frontmatter_lines)
    content += "\n\n"
    if backlink_line:
        content += backlink_line + "\n\n"
    content += "## Summary\n\n" + (doc.summary.strip() or "(no summary)") + "\n\n"
    content += "## Body Excerpt\n\n" + (doc.body_excerpt.strip() or "(empty)") + "\n"

    out_path.write_text(content, encoding="utf-8")
    return out_path
