from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from webmail_summary.index.db import get_conn
from webmail_summary.index.mail_repo import set_analysis, set_daily_overview, upsert_message
from webmail_summary.index.settings import set_setting


def _app_data_dir(tmp_path):
    return tmp_path / "WebmailSummary"


def _mk_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from webmail_summary.app.main import create_app
    from webmail_summary.ui import routes_home

    monkeypatch.setattr(routes_home, "_check_github_release", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        routes_home,
        "check_local_ready",
        lambda model_id: SimpleNamespace(engine_ok=True, model_ok=True),
    )
    monkeypatch.setattr(routes_home, "is_ai_ready", lambda settings: True)
    monkeypatch.setattr(routes_home, "is_setup_complete", lambda settings: True)
    return create_app()


def _seed_ui_data(tmp_path):
    conn = get_conn(_app_data_dir(tmp_path) / "db.sqlite3")
    try:
        set_setting(conn, "imap_host", "imap.example.com")
        set_setting(conn, "imap_user", "user@example.com")
        set_setting(conn, "ui_theme", "bento")
        set_daily_overview(conn, "2026-04-16", "overview for 04-16")
        set_daily_overview(conn, "2026-04-17", "overview for 04-17")

        bad_id = upsert_message(
            conn,
            account_id="acct",
            mailbox="INBOX",
            uidvalidity=1,
            uid=1,
            message_id="<bad-1>",
            internal_date="2026-04-16T09:48:19+09:00",
            from_addr="sender@example.com",
            to_addr="user@example.com",
            subject="Bad summary message",
            raw_eml_path="C:/mail/bad.eml",
            body_html_path=None,
            body_text_path=None,
            rendered_html_path=None,
        )
        set_analysis(
            conn,
            message_fk=bad_id,
            summary="(no summary)",
            tags=[],
            topics=[],
            personal=False,
            summarize_ms=1200,
        )

        good_id = upsert_message(
            conn,
            account_id="acct",
            mailbox="INBOX",
            uidvalidity=1,
            uid=2,
            message_id="<good-1>",
            internal_date="2026-04-16T10:00:00+09:00",
            from_addr="sender@example.com",
            to_addr="user@example.com",
            subject="Healthy summary message",
            raw_eml_path="C:/mail/good.eml",
            body_html_path=None,
            body_text_path=None,
            rendered_html_path=None,
        )
        set_analysis(
            conn,
            message_fk=good_id,
            summary="핵심 요약\n- 정상 동작 중입니다.",
            tags=[],
            topics=[],
            personal=False,
            summarize_ms=800,
        )

        next_day_id = upsert_message(
            conn,
            account_id="acct",
            mailbox="INBOX",
            uidvalidity=1,
            uid=3,
            message_id="<good-2>",
            internal_date="2026-04-17T08:30:00+09:00",
            from_addr="sender@example.com",
            to_addr="user@example.com",
            subject="Next day summary message",
            raw_eml_path="C:/mail/next.eml",
            body_html_path=None,
            body_text_path=None,
            rendered_html_path=None,
        )
        set_analysis(
            conn,
            message_fk=next_day_id,
            summary="핵심 요약\n- 다음 날 메일입니다.",
            tags=[],
            topics=[],
            personal=False,
            summarize_ms=700,
        )

        conn.commit()
        return bad_id, good_id
    finally:
        conn.close()


def test_home_days_api_reports_failed_counts_and_fallback_notice(tmp_path, monkeypatch):
    app = _mk_app(tmp_path, monkeypatch)
    _seed_ui_data(tmp_path)
    client = TestClient(app)

    r = client.get("/api/ui/days")

    assert r.status_code == 200
    days = r.json()
    assert days[0]["day"] == "2026-04-17"
    assert days[0]["failed_count"] == 0
    assert days[1]["day"] == "2026-04-16"
    assert days[1]["failed_count"] == 1

    home = client.get("/?ui_notice=native_fallback&ui_reason=RuntimeError")

    assert home.status_code == 200
    assert 'id="btn-retry-failed-day"' in home.text
    assert "앱 창 대신 브라우저 모드로 열렸습니다." in home.text
    assert "오류 요약" in home.text
    assert "RuntimeError" in home.text


def test_day_view_shows_single_retry_only_for_failed_summary(tmp_path, monkeypatch):
    app = _mk_app(tmp_path, monkeypatch)
    bad_id, good_id = _seed_ui_data(tmp_path)
    client = TestClient(app)

    r = client.get("/day/2026-04-16")

    assert r.status_code == 200
    html = r.text
    assert html.count('class="btn btn--secondary btn-retry-single"') == 1
    assert f'data-message-id="{bad_id}" data-needs-resummarize="1"' in html
    assert f'data-message-id="{good_id}" data-needs-resummarize="0"' in html
    assert "이 항목 다시 요약" in html
