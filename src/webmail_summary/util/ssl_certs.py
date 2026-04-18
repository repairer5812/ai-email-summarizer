from __future__ import annotations

import os
import sys


def _is_under_dir(path: str, parent: str) -> bool:
    try:
        child_norm = os.path.normcase(os.path.abspath(path))
        parent_norm = os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([child_norm, parent_norm]) == parent_norm
    except Exception:
        return False


def _is_usable_cert_path(path: str) -> bool:
    p = str(path or "").strip()
    if not p:
        return False
    if not os.path.exists(p):
        return False
    if "_MEI" not in p:
        return True
    current_meipass = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if not current_meipass:
        return False
    return _is_under_dir(p, current_meipass)


def configure_requests_ca_bundle() -> str:
    """Best-effort TLS CA bundle configuration for frozen builds.

    PyInstaller onefile builds sometimes miss certifi's cacert.pem unless it is
    explicitly collected. This sets env vars that requests/urllib3 honor.
    """

    try:
        import certifi

        ca_path = str(certifi.where() or "").strip()
        if ca_path and os.path.exists(ca_path):
            cur_ssl = os.environ.get("SSL_CERT_FILE", "")
            cur_req = os.environ.get("REQUESTS_CA_BUNDLE", "")

            # Preserve explicit valid overrides, but replace broken/stale _MEI paths.
            if not _is_usable_cert_path(cur_ssl):
                os.environ["SSL_CERT_FILE"] = ca_path
            if not _is_usable_cert_path(cur_req):
                os.environ["REQUESTS_CA_BUNDLE"] = ca_path
            return ca_path
    except Exception:
        pass
    return ""
