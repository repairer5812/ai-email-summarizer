from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from webmail_summary.index.db import get_conn, init_db
from webmail_summary.index.mail_repo import set_analysis, upsert_message
from webmail_summary.jobs import repo
from webmail_summary.llm.base import LlmResult


def _app_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "WebmailSummary"


def _mk_app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from webmail_summary.app.main import create_app

    return create_app()


def _seed_message(
    conn,
    *,
    uid: int,
    day: str,
    subject: str,
    summary: str,
    archive_root: Path,
) -> int:
    msg_dir = archive_root / f"msg-{uid}"
    msg_dir.mkdir(parents=True, exist_ok=True)
    (msg_dir / "body.txt").write_text(f"body for {subject}", encoding="utf-8")

    msg_id = upsert_message(
        conn,
        account_id="acct",
        mailbox="INBOX",
        uidvalidity=1,
        uid=uid,
        message_id=f"<{uid}@example.com>",
        internal_date=f"{day}T09:00:00+09:00",
        from_addr="sender@example.com",
        to_addr="user@example.com",
        subject=subject,
        raw_eml_path=str(msg_dir / "raw.eml"),
        body_html_path=None,
        body_text_path=str(msg_dir / "body.txt"),
        rendered_html_path=None,
    )
    set_analysis(
        conn,
        message_fk=msg_id,
        summary=summary,
        tags=[],
        topics=[],
        personal=False,
        summarize_ms=1000,
    )
    return msg_id


def test_resummarize_endpoint_accepts_multiple_dates(tmp_path, monkeypatch):
    app = _mk_app(tmp_path, monkeypatch)
    client = TestClient(app)

    from webmail_summary.api import routes_jobs

    captured: dict[str, object] = {}

    class _Runner:
        def enqueue(self, *, kind, fn):
            captured["kind"] = kind
            captured["fn"] = fn
            return "job-123"

    def _fake_task(**kwargs):
        captured["kwargs"] = kwargs
        return lambda *_args, **_kwargs: None

    monkeypatch.setattr(routes_jobs, "get_runner", lambda: _Runner())
    monkeypatch.setattr(routes_jobs, "resummarize_day_task", _fake_task)

    r = client.post(
        "/api/jobs/resummarize-day",
        json={
            "date_keys": ["2026-04-16", "2026-04-17"],
            "only_failed": True,
        },
    )

    assert r.status_code == 200
    assert r.json()["job_id"] == "job-123"
    assert captured["kind"] == "resummarize-day"
    assert captured["kwargs"] == {
        "date_key": "",
        "date_keys": ["2026-04-16", "2026-04-17"],
        "only_failed": True,
        "message_ids": None,
    }


def test_resummarize_endpoint_rejects_message_ids_with_multiple_dates(
    tmp_path, monkeypatch
):
    app = _mk_app(tmp_path, monkeypatch)
    client = TestClient(app)

    r = client.post(
        "/api/jobs/resummarize-day",
        json={
            "date_keys": ["2026-04-16", "2026-04-17"],
            "message_ids": [1, 2],
        },
    )

    assert r.status_code == 400
    assert r.json()["error"] == "message_ids require exactly one date"


def test_multi_day_failed_resummarize_processes_only_failed_messages(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from webmail_summary.jobs import tasks_resummarize as mod

    db_path = _app_data_dir(tmp_path) / "db.sqlite3"
    init_db(db_path)

    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    conn = get_conn(db_path)
    try:
        _seed_message(
            conn,
            uid=1,
            day="2026-04-16",
            subject="failed-a",
            summary="(no summary)",
            archive_root=archive_root,
        )
        _seed_message(
            conn,
            uid=2,
            day="2026-04-16",
            subject="healthy-a",
            summary="- already good",
            archive_root=archive_root,
        )
        _seed_message(
            conn,
            uid=3,
            day="2026-04-17",
            subject="failed-b",
            summary="(LLM timeout)",
            archive_root=archive_root,
        )
        repo.create_job(conn, job_id="job-1", kind="resummarize-day")
    finally:
        conn.close()

    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    settings = SimpleNamespace(
        obsidian_root=str(vault_root),
        sender_filter="",
        cloud_provider="",
        openrouter_model="",
        user_roles="",
        user_interests="",
    )

    class _Provider:
        tier = "standard"

    provider = _Provider()
    refreshed_days: list[str] = []
    daily_note_days: list[str] = []
    summarized_subjects: list[str] = []
    progress_messages: list[str] = []

    monkeypatch.setattr(mod, "load_settings", lambda conn: settings)
    monkeypatch.setattr(mod, "get_llm_provider", lambda _settings: provider)

    def _fake_summarize(
        _provider,
        *,
        subject,
        body,
        on_detail,
        on_progress,
        user_profile,
    ):
        summarized_subjects.append(subject)
        on_progress(1.0)
        return LlmResult(
            summary=f"- {subject} updated",
            tags=[],
            backlinks=[],
            personal=False,
        )

    def _fake_refresh_overviews_for_dates(
        *,
        db_path,
        provider,
        settings,
        date_keys,
        force_refresh,
        job_id,
    ):
        refreshed_days.extend(date_keys)
        return list(date_keys)

    def _fake_export_email_note(*, vault_root, inp):
        return (
            Path(vault_root)
            / "Mail"
            / f"{inp.date:%Y-%m}"
            / mod.email_note_filename(inp.date, inp.subject, inp.message_key)
        )

    def _fake_export_daily_note(*, vault_root, date, message_notes, daily_summary):
        daily_note_days.append(date.isoformat())
        return Path(vault_root) / "Daily" / f"{date:%Y-%m-%d}.md"

    original_update_progress = mod.repo.update_progress

    def _capture_update_progress(conn, *, job_id, current, total, message):
        progress_messages.append(str(message))
        return original_update_progress(
            conn,
            job_id=job_id,
            current=current,
            total=total,
            message=message,
        )

    monkeypatch.setattr(mod, "summarize_email_long_aware", _fake_summarize)
    monkeypatch.setattr(mod, "refresh_overviews_for_dates", _fake_refresh_overviews_for_dates)
    monkeypatch.setattr(mod, "export_email_note", _fake_export_email_note)
    monkeypatch.setattr(mod, "export_daily_note", _fake_export_daily_note)
    monkeypatch.setattr(mod.repo, "update_progress", _capture_update_progress)

    run = mod.resummarize_day_task(
        date_keys=["2026-04-16", "2026-04-17"],
        only_failed=True,
    )
    run("job-1", threading.Event())

    assert summarized_subjects == ["failed-a", "failed-b"]
    assert sorted(refreshed_days) == ["2026-04-16", "2026-04-17"]
    assert sorted(daily_note_days) == ["2026-04-16", "2026-04-17"]
    assert progress_messages
    assert all(not msg.startswith("[") for msg in progress_messages)

    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT subject, summary FROM messages ORDER BY uid ASC"
        ).fetchall()
    finally:
        conn.close()

    assert rows[0]["summary"] == "- failed-a updated"
    assert rows[1]["summary"] == "- already good"
    assert rows[2]["summary"] == "- failed-b updated"
