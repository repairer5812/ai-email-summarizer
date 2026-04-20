from __future__ import annotations


def _preload_cffi_backend() -> None:
    try:
        from webmail_summary.ui.frozen_extensions import preload_cffi_backend
    except Exception:
        return

    try:
        preload_cffi_backend()
    except Exception:
        return


_preload_cffi_backend()
