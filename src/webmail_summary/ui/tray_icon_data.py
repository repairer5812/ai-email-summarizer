r"""Tray icon image embedded as base64 inside Python source.

Why embedded instead of a regular static file?

A user on Windows 11 (Insider 26200) reported that v0.6.6.22's tray icon
never appeared. Forensic analysis showed:

  * The PyInstaller archive inside the user's installed EXE DID contain
    `webmail_summary/ui/static/app-icon.png` at the correct 6,368,586 byte
    size (verified with PyInstaller.archive.readers.CArchiveReader).
  * The installed EXE's SHA256 matched the published SHA256SUMS exactly,
    ruling out installer-side modification or download corruption.
  * The CI smoke test confirmed the unsigned EXE serves `/static/app-icon.png`
    over HTTP with 200 + 6,368,586 bytes.
  * Yet on the user's machine, `_MEI<random>/webmail_summary/ui/static/app-icon.png`
    was missing from the PyInstaller extraction directory, while smaller
    sibling files (`app.css`, `app.js`) were present and served correctly.

The only remaining explanation is that an external agent on the user's
machine (Windows Defender / EDR / antivirus heuristic) deletes the
6 MB PNG immediately after PyInstaller extracts it to `%TEMP%\_MEI*\`,
before the app gets a chance to read it. We cannot control external
security tools, and we cannot reduce the master `app-icon.png` size
without losing favicon quality elsewhere.

So the tray-icon-specific image lives here, as base64 inside source:

  * It's 64×64 (sufficient for HiDPI tray rendering), ~7 KB raw / ~9 KB
    base64. Small enough that no realistic AV heuristic targets it.
  * It rides inside the PyInstaller PYZ archive (the bytecode bundle),
    not as a separately-extracted data file. Python source/bytecode is
    loaded into memory by the PyInstaller bootstrap and never touches
    a path under `_MEI*` that an external tool can quarantine.
  * `_load_tray_image()` decodes this in-memory string with stdlib
    `base64` and Pillow — no file system access, no `importlib.resources`,
    no `--collect-data` heuristic, no signing-archive interaction.

To regenerate (e.g., if the master icon design changes):

    python -c "from PIL import Image; from io import BytesIO; import base64
    src = Image.open('src/webmail_summary/ui/static/app-icon.png').convert('RGBA')
    src.thumbnail((64, 64), Image.LANCZOS)
    buf = BytesIO(); src.save(buf, format='PNG', optimize=True)
    print(base64.b64encode(buf.getvalue()).decode())"
"""

from __future__ import annotations


TRAY_ICON_PNG_BASE64: str = (
    "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"
    "AElFTkSuQmCC"
)
