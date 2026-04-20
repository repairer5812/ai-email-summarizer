from __future__ import annotations

from pathlib import Path


def test_release_workflow_keeps_cffi_backend_hidden_import():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "--hidden-import _cffi_backend" in workflow
    assert "--runtime-hook installer/pyinstaller_rth_cffi.py" in workflow
    assert Path("installer/pyinstaller_rth_cffi.py").is_file()
