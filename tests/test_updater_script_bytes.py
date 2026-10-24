"""Pin the bytes of the updater script that ui/updates.py writes.

apply_update.ps1 is written next to the downloaded installer and run with
`powershell -File`. Moving its source text around must not change what
lands on disk: same text, UTF-8 with exactly one BOM, platform newlines.
"""

from __future__ import annotations

import codecs
import hashlib
import os
from pathlib import Path

from webmail_summary.ui.updates import _write_updater_script

# sha256 of the script text after the BOM, with CRLF folded to LF
# (recorded from the inline string in ui/updates.py before the move).
EXPECTED_TEXT_SHA256 = "9fb742b772287c6b222641a1a22f46b92cf2ead254dabca9ced14816ca456c4d"
EXPECTED_TEXT_BYTES = 5929
EXPECTED_LINES = 188


def test_written_updater_script_is_unchanged(tmp_path: Path):
    path = tmp_path / "apply_update.ps1"
    _write_updater_script(path)
    raw = path.read_bytes()

    assert raw.startswith(codecs.BOM_UTF8)
    body = raw[len(codecs.BOM_UTF8):]
    assert not body.startswith(codecs.BOM_UTF8)

    newline = os.linesep.encode("ascii")
    if newline == b"\n":
        assert b"\r" not in body
    else:
        assert body.count(b"\r\n") == body.count(b"\n")

    text = body.replace(b"\r\n", b"\n")
    assert len(text) == EXPECTED_TEXT_BYTES
    assert text.count(b"\n") == EXPECTED_LINES
    assert text.endswith(b"}\n")
    assert hashlib.sha256(text).hexdigest() == EXPECTED_TEXT_SHA256
