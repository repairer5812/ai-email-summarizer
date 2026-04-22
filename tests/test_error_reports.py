from __future__ import annotations

from pathlib import Path

from webmail_summary.util import error_reports


def test_write_error_report_prefers_desktop_and_redacts_sensitive_details(
    monkeypatch, tmp_path
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(error_reports, "_app_version", lambda: "9.9.9")

    report_path = error_reports.write_error_report(
        category="imap-test",
        title="IMAP test failed",
        summary="TLS handshake failed",
        details={
            "imap_host": "imap.example.com",
            "api_key": "super-secret",
            "password_hint": "do-not-write",
        },
        related_paths=[log_path],
    )

    assert report_path.parent == desktop / "WebmailSummary Error Reports"
    text = report_path.read_text(encoding="utf-8")
    assert "Webmail Summary Error Report" in text
    assert "App version: 9.9.9" in text
    assert "- imap_host: imap.example.com" in text
    assert "- api_key: (redacted)" in text
    assert "- password_hint: (redacted)" in text
    assert "===== Tail: server.log =====" in text
    assert "line3" in text


def test_mask_email_address_keeps_domain():
    assert error_reports.mask_email_address("user@example.com") == "u***r@example.com"
    assert error_reports.mask_email_address("a@example.com") == "a***@example.com"
