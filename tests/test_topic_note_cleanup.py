"""Tests for topic note stale link cleanup during resummarize.

Verifies that when a message's topic changes from A to B:
1. Topic A note removes the stale link (or is deleted if empty)
2. Topic B note gains the new link
3. email_note_filename produces consistent paths for matching
"""
from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from webmail_summary.export.obsidian.exporter import (
    email_note_filename,
    export_email_note,
    export_topic_note,
    MessageExportInput,
)
from webmail_summary.export.obsidian.naming import safe_topic_name


def _make_vault(tmp: Path) -> Path:
    vault = tmp / "vault"
    vault.mkdir()
    return vault


def _make_archive(tmp: Path, key: str) -> Path:
    """Create a minimal archive dir with a body.txt."""
    d = tmp / "archive" / key
    d.mkdir(parents=True)
    (d / "body.txt").write_text("test body", encoding="utf-8")
    return d


def test_email_note_filename_is_deterministic():
    """Same inputs always produce the same filename."""
    d = dt.date(2026, 4, 17)
    f1 = email_note_filename(d, "Hello World", "acct-123456789-42")
    f2 = email_note_filename(d, "Hello World", "acct-123456789-42")
    assert f1 == f2
    assert f1.endswith(".md")
    assert "2026-04-17" in f1


def test_email_note_filename_includes_short_key():
    """The last 12 chars of message_key appear in the filename."""
    key = "myaccount-1672531200-12345"
    fname = email_note_filename(dt.date(2026, 1, 1), "Test", key)
    short = key[-12:]
    assert short in fname


def test_topic_note_replace_removes_stale_links():
    """Replace mode rebuilds topic note from only the provided notes."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp))
        archive = _make_archive(Path(tmp), "a-100-1")

        # Create two email notes
        note1 = export_email_note(
            vault_root=vault,
            inp=MessageExportInput(
                message_key="a-100-1",
                date=dt.date(2026, 4, 17),
                sender="x@x.com",
                subject="Mail A",
                summary="summary A",
                tags=[],
                topics=["TopicX"],
                archive_dir=archive,
            ),
        )
        archive2 = _make_archive(Path(tmp), "a-100-2")
        note2 = export_email_note(
            vault_root=vault,
            inp=MessageExportInput(
                message_key="a-100-2",
                date=dt.date(2026, 4, 17),
                sender="y@y.com",
                subject="Mail B",
                summary="summary B",
                tags=[],
                topics=["TopicX"],
                archive_dir=archive2,
            ),
        )

        # Build topic note with both notes (merge)
        export_topic_note(
            vault_root=vault, topic="TopicX", message_notes=[note1, note2]
        )
        topic_file = vault / "Topic" / f"{safe_topic_name('TopicX')}.md"
        assert topic_file.exists()
        content = topic_file.read_text(encoding="utf-8")
        assert "Mail A" in content or "a-100-1" in content
        assert "Mail B" in content or "a-100-2" in content

        # Now replace with only note2 (simulating topic change for mail A)
        export_topic_note(
            vault_root=vault,
            topic="TopicX",
            message_notes=[note2],
            replace=True,
        )
        content2 = topic_file.read_text(encoding="utf-8")
        # note1 link should be gone
        assert "a-100-1" not in content2
        # note2 link should remain
        assert "a-100-2" in content2 or "Mail B" in content2


def test_topic_note_replace_empty_deletes_nothing():
    """Replace with empty list creates an empty topic note (not delete)."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp))

        export_topic_note(
            vault_root=vault,
            topic="EmptyTopic",
            message_notes=[],
            replace=True,
        )
        topic_file = vault / "Topic" / f"{safe_topic_name('EmptyTopic')}.md"
        assert topic_file.exists()
        content = topic_file.read_text(encoding="utf-8")
        assert "## Messages" in content


def test_topic_note_merge_preserves_existing():
    """Merge mode adds new links without removing existing ones."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp))
        archive1 = _make_archive(Path(tmp), "a-100-1")
        archive2 = _make_archive(Path(tmp), "a-100-2")

        note1 = export_email_note(
            vault_root=vault,
            inp=MessageExportInput(
                message_key="a-100-1",
                date=dt.date(2026, 4, 17),
                sender="x@x.com",
                subject="First",
                summary="s1",
                tags=[],
                topics=["MergeTopic"],
                archive_dir=archive1,
            ),
        )
        # First sync batch
        export_topic_note(
            vault_root=vault, topic="MergeTopic", message_notes=[note1]
        )

        note2 = export_email_note(
            vault_root=vault,
            inp=MessageExportInput(
                message_key="a-100-2",
                date=dt.date(2026, 4, 17),
                sender="y@y.com",
                subject="Second",
                summary="s2",
                tags=[],
                topics=["MergeTopic"],
                archive_dir=archive2,
            ),
        )
        # Second sync batch (merge)
        export_topic_note(
            vault_root=vault, topic="MergeTopic", message_notes=[note2]
        )

        topic_file = vault / "Topic" / f"{safe_topic_name('MergeTopic')}.md"
        content = topic_file.read_text(encoding="utf-8")
        # Both links should be present
        assert "a-100-1" in content or "First" in content
        assert "a-100-2" in content or "Second" in content
