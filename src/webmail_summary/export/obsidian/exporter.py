from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path

from webmail_summary.export.obsidian.naming import safe_filename, safe_topic_name
from webmail_summary.util.atomic_io import atomic_write_text


@dataclass(frozen=True)
class MessageExportInput:
    message_key: str
    date: dt.date
    sender: str
    subject: str
    summary: str
    tags: list[str]
    topics: list[str]
    archive_dir: Path


def email_note_filename(date: dt.date, subject: str, message_key: str) -> str:
    """Build the canonical filename for an email note."""
    short_key = message_key[-12:].replace("/", "-").replace("\\", "-")
    return f"{date:%Y-%m-%d} - {safe_filename(subject)} ({short_key}).md"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _wikilink_for(vault_root: Path, note_path: Path) -> str:
    try:
        rel = note_path.relative_to(vault_root)
    except Exception:
        rel = note_path.name
    s = str(rel).replace("\\", "/")
    if s.lower().endswith(".md"):
        s = s[:-3]
    return f"[[{s}]]"


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    _ensure_dir(dst)
    for item in src.iterdir():
        if item.is_dir():
            _copy_tree(item, dst / item.name)
        else:
            (dst / item.name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / item.name)


def export_email_note(*, vault_root: Path, inp: MessageExportInput) -> Path:
    # Layout
    mail_dir = vault_root / "Mail" / f"{inp.date:%Y-%m}"
    assets_dir = vault_root / "Assets" / inp.message_key
    raw_dir = vault_root / "Raw"
    _ensure_dir(mail_dir)
    _ensure_dir(assets_dir)
    _ensure_dir(raw_dir)

    # Copy archived assets into vault
    # Expect archive_dir contains: raw.eml, rendered.html, body.*, attachments/, external/
    for name in ["rendered.html", "body.html", "body.txt"]:
        src = inp.archive_dir / name
        if src.exists():
            shutil.copy2(src, assets_dir / name)

    _copy_tree(inp.archive_dir / "attachments", assets_dir / "attachments")
    _copy_tree(inp.archive_dir / "external", assets_dir / "external")

    raw_src = inp.archive_dir / "raw.eml"
    if raw_src.exists():
        shutil.copy2(raw_src, raw_dir / f"{inp.message_key}.eml")

    # Build markdown
    tags = [t.strip().lstrip("#") for t in inp.tags if t.strip()]
    topics = [safe_topic_name(t) for t in inp.topics if t.strip()]

    daily_link = f"[[Daily/{inp.date:%Y-%m-%d}]]"
    topic_links = " ".join([f"[[Topic/{t}]]" for t in topics])

    front = [
        "---",
        f"title: {inp.subject}",
        f"date: {inp.date:%Y-%m-%d}",
        f"sender: {inp.sender}",
        f"message_key: {inp.message_key}",
        "tags:",
    ]
    for t in tags:
        front.append(f"  - {t}")
    front.append("topics:")
    for t in topics:
        front.append(f"  - {t}")
    front.append("---")

    body = "\n".join(front) + "\n\n"
    body += f"{daily_link} {topic_links}\n\n"
    body += (
        "## 핵심 요약 / 상세 요약\n\n"
        + (inp.summary.strip() or "(no summary)")
        + "\n\n"
    )
    body += "## Original\n\n"
    body += f"- Rendered HTML: [[Assets/{inp.message_key}/rendered.html]]\n"
    body += f"- Raw EML: [[Raw/{inp.message_key}.eml]]\n"

    # Embed inline images if present (best-effort)
    attach_dir = assets_dir / "attachments"
    if attach_dir.exists():
        exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        imgs = [
            p for p in attach_dir.iterdir() if p.is_file() and p.suffix.lower() in exts
        ]
        if imgs:
            body += "\n## Images\n\n"
            for p in imgs[:20]:
                body += f"![[Assets/{inp.message_key}/attachments/{p.name}]]\n"

    fname = email_note_filename(inp.date, inp.subject, inp.message_key)
    out_path = mail_dir / fname
    atomic_write_text(out_path, body)
    return out_path


def _extract_existing_links(file_path: Path) -> set[str]:
    """Extract existing wikilinks from a note file."""
    if not file_path.exists():
        return set()
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        import re

        return set(re.findall(r"\[\[([^\]]+)\]\]", text))
    except Exception:
        return set()


def export_daily_note(
    *,
    vault_root: Path,
    date: dt.date,
    message_notes: list[Path],
    daily_summary: str,
) -> Path:
    daily_dir = vault_root / "Daily"
    _ensure_dir(daily_dir)
    out_path = daily_dir / f"{date:%Y-%m-%d}.md"

    # Merge: keep existing links and add new ones.
    existing_links = _extract_existing_links(out_path)
    new_links = [_wikilink_for(vault_root, p) for p in message_notes]
    # Parse existing link targets for dedup
    all_links: list[str] = []
    seen: set[str] = set()
    # Existing links first
    for link in sorted(existing_links):
        target = link.replace("[[", "").replace("]]", "")
        if target not in seen:
            seen.add(target)
            all_links.append(f"[[{target}]]")
    # New links
    for link in new_links:
        target = link.replace("[[", "").replace("]]", "")
        if target not in seen:
            seen.add(target)
            all_links.append(link)

    front = ["---", f"date: {date:%Y-%m-%d}", "---"]
    body = "\n".join(front) + "\n\n"
    body += "## Daily Digest\n\n" + (daily_summary.strip() or "(no digest)") + "\n\n"
    body += "## Messages\n\n"
    for link in all_links:
        body += f"- {link}\n"
    atomic_write_text(out_path, body)
    return out_path


def export_topic_note(
    *,
    vault_root: Path,
    topic: str,
    message_notes: list[Path],
    replace: bool = False,
) -> Path:
    """Export a topic note.

    When *replace* is True the note is rebuilt from *message_notes* only
    (no merge with existing links).  Use this when cleaning up stale topics.
    """
    topic_dir = vault_root / "Topic"
    _ensure_dir(topic_dir)
    name = safe_topic_name(topic)
    out_path = topic_dir / f"{name}.md"

    if replace:
        # Replace mode: only use the provided notes (for stale cleanup).
        all_links = [_wikilink_for(vault_root, p) for p in message_notes]
    else:
        # Merge: keep existing links and add new ones.
        existing_links = _extract_existing_links(out_path)
        new_links = [_wikilink_for(vault_root, p) for p in message_notes]
        all_links = []
        seen: set[str] = set()
        for link in sorted(existing_links):
            target = link.replace("[[", "").replace("]]", "")
            if target not in seen:
                seen.add(target)
                all_links.append(f"[[{target}]]")
        for link in new_links:
            target = link.replace("[[", "").replace("]]", "")
            if target not in seen:
                seen.add(target)
                all_links.append(link)

    front = ["---", f"topic: {name}", "---"]
    body = "\n".join(front) + "\n\n"
    body += "## Messages\n\n"
    for link in all_links:
        body += f"- {link}\n"
    atomic_write_text(out_path, body)
    return out_path
