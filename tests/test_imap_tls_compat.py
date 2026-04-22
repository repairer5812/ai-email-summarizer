from __future__ import annotations

import ssl

from fastapi.testclient import TestClient

import webmail_summary.imap_client as imap_client


def _mk_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from webmail_summary.app.main import create_app

    return create_app()


def test_imap_session_retries_tls_eof_with_tls12_context(monkeypatch):
    attempts: list[object] = []

    class _FakeClient:
        def __init__(
            self,
            host,
            port=None,
            use_uid=True,
            ssl=True,
            stream=False,
            ssl_context=None,
            timeout=None,
        ):
            self.host = host
            self.port = port
            self.ssl_context = ssl_context
            self.timeout = timeout
            attempts.append(self)

        def login(self, user, password):
            if len(attempts) == 1:
                raise ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:2427)")

        def logout(self):
            return None

    monkeypatch.setattr(imap_client, "IMAPClient", _FakeClient)

    with imap_client.ImapSession("imap.example.com", 993, "user", "pw") as session:
        assert session._tls_mode == "tls12_compat"

    assert len(attempts) == 2
    assert attempts[0].timeout == 20
    assert attempts[1].timeout == 20
    assert attempts[1].ssl_context.maximum_version == ssl.TLSVersion.TLSv1_2


def test_describe_imap_connection_error_mentions_ssl_inspection():
    text = imap_client.describe_imap_connection_error(
        ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:2427)")
    )

    assert "TLS handshake" in text
    assert "SSL inspection" in text


def test_setup_test_imap_returns_tls_guidance(tmp_path, monkeypatch):
    app = _mk_app(tmp_path, monkeypatch)
    from webmail_summary.ui import routes_setup
    report_path = tmp_path / "reports" / "imap-tls.txt"

    class _BrokenSession:
        def __init__(self, host, port, user, password):
            self.host = host

        def __enter__(self):
            raise ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:2427)")

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(routes_setup, "ImapSession", _BrokenSession)
    monkeypatch.setattr(routes_setup, "write_error_report", lambda **kwargs: report_path)

    client = TestClient(app)
    r = client.post(
        "/setup/test-imap",
        data={
            "imap_host": "imap.example.com",
            "imap_port": "993",
            "imap_user": "user@example.com",
            "imap_password": "pw",
        },
    )

    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert j["kind"] == "tls"
    assert "TLS" in j["message"]
    assert "SSL inspection" in j["message"]
    assert str(report_path) in j["message"]


def test_setup_test_imap_network_error_mentions_report_path(tmp_path, monkeypatch):
    app = _mk_app(tmp_path, monkeypatch)
    from webmail_summary.ui import routes_setup

    report_path = tmp_path / "reports" / "imap-network.txt"

    class _BrokenSession:
        def __init__(self, host, port, user, password):
            self.host = host

        def __enter__(self):
            raise OSError("connection reset by peer")

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(routes_setup, "ImapSession", _BrokenSession)
    monkeypatch.setattr(routes_setup, "write_error_report", lambda **kwargs: report_path)

    client = TestClient(app)
    r = client.post(
        "/setup/test-imap",
        data={
            "imap_host": "imap.example.com",
            "imap_port": "993",
            "imap_user": "user@example.com",
            "imap_password": "pw",
        },
    )

    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert j["kind"] == "network"
    assert str(report_path) in j["message"]
