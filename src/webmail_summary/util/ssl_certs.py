from __future__ import annotations

import os


def configure_requests_ca_bundle() -> str:
    """Best-effort TLS CA bundle configuration for frozen builds.

    PyInstaller onefile builds sometimes miss certifi's cacert.pem unless it is
    explicitly collected. This sets env vars that requests/urllib3 honor.
    """

    try:
        import certifi

        ca_path = str(certifi.where() or "").strip()
        if ca_path and os.path.exists(ca_path):
            os.environ.setdefault("SSL_CERT_FILE", ca_path)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
            return ca_path
    except Exception:
        pass
    return ""
