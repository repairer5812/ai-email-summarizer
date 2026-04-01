from __future__ import annotations

import sqlite3

from webmail_summary.index.settings import Settings
from webmail_summary.jobs.tasks_refresh_overviews import refresh_overviews_for_dates


class _DummyProvider:
    @property
    def tier(self) -> str:
        return "standard"


def _settings() -> Settings:
    return Settings(
        imap_host="",
        imap_port=993,
        imap_user="",
        imap_folder="INBOX",
        sender_filter="",
        obsidian_root="",
        llm_backend="local",
        cloud_provider="openai",
        cloud_multimodal_enabled=False,
        openrouter_model="openai/gpt-4o-mini",
        local_model_id="fast",
        external_max_bytes=0,
        revert_seen_after_sync=False,
        user_roles=[],
        user_interests="",
        ui_theme="bento",
        close_behavior="background",
        update_channel="stable",
        update_latest_version="",
        update_auto_check_enabled=True,
        update_repo="",
        update_snooze_until="",
        update_skip_version="",
        update_last_checked_at="",
        update_download_url="",
        update_last_check_status="",
    )


def _mk_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE messages (internal_date TEXT, summary TEXT, summarized_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE daily_overviews (day TEXT PRIMARY KEY, overview TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE job_events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, level TEXT, text TEXT)"
    )
    conn.commit()
    conn.close()


def test_refresh_overviews_for_dates_updates_selected_day(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite3"
    _mk_db(db)

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO messages(internal_date, summary, summarized_at) VALUES (?, ?, ?)",
        ("2026-03-30T10:00:00+09:00", "- 첫 메일", "2026-03-30T10:05:00+09:00"),
    )
    conn.execute(
        "INSERT INTO messages(internal_date, summary, summarized_at) VALUES (?, ?, ?)",
        ("2026-03-30T11:00:00+09:00", "- 두번째 메일", "2026-03-30T11:05:00+09:00"),
    )
    conn.commit()
    conn.close()

    import webmail_summary.jobs.tasks_refresh_overviews as mod

    monkeypatch.setattr(
        mod,
        "synthesize_daily_overview",
        lambda provider,
        day,
        summaries,
        user_profile=None: f"- {day} ({len(summaries)})",
    )

    refreshed = refresh_overviews_for_dates(
        db_path=db,
        provider=_DummyProvider(),
        settings=_settings(),
        date_keys=["2026-03-30"],
        force_refresh=True,
        job_id=None,
    )

    assert refreshed == ["2026-03-30"]
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT overview FROM daily_overviews WHERE day=?", ("2026-03-30",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "- 2026-03-30 (2)"


def test_refresh_overviews_for_dates_skips_up_to_date_day(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite3"
    _mk_db(db)

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO messages(internal_date, summary, summarized_at) VALUES (?, ?, ?)",
        ("2026-03-30T10:00:00+09:00", "- 첫 메일", "2026-03-30T10:05:00+09:00"),
    )
    conn.execute(
        "INSERT INTO daily_overviews(day, overview, updated_at) VALUES (?, ?, ?)",
        ("2026-03-30", "- 기존 개요", "2026-03-30T12:00:00+09:00"),
    )
    conn.commit()
    conn.close()

    import webmail_summary.jobs.tasks_refresh_overviews as mod

    monkeypatch.setattr(
        mod,
        "synthesize_daily_overview",
        lambda provider, day, summaries, user_profile=None: "- 새 개요",
    )

    refreshed = refresh_overviews_for_dates(
        db_path=db,
        provider=_DummyProvider(),
        settings=_settings(),
        date_keys=["2026-03-30"],
        force_refresh=False,
        job_id=None,
    )

    assert refreshed == []
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT overview FROM daily_overviews WHERE day=?", ("2026-03-30",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "- 기존 개요"
