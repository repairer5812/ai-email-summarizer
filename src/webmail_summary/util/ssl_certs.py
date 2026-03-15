from __future__ import annotations

import os


def _is_usable_cert_path(path: str) -> bool:
    p = str(path or "").strip()
    if not p:
        return False
    if "_MEI" in p and not os.path.exists(p):
        return False
    return os.path.exists(p)


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
