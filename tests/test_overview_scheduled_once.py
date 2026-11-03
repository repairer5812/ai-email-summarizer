"""A successful sync schedules one overview pass for the days it touched."""

from __future__ import annotations

import threading

from webmail_summary.index.db import app_db_path, init_db, open_db
from webmail_summary.index.mail_repo import set_analysis, upsert_message
from webmail_summary.jobs import repo
from webmail_summary.jobs.runner import JobRunner
from webmail_summary.jobs.tasks_refresh_overviews import (
    format_overview_dates_event,
    overview_dates_for_sync_job,
    refresh_overviews_task,
)
from webmail_summary.llm.base import LlmProvider
from webmail_summary.llm.long_summarize import synthesize_daily_overview
from webmail_summary.llm.summary_quality import SUMMARY_LLM_CALL_FAILED


def _seed_mail(conn, *, uid: int, day: str, summary: str) -> None:
    fk = upsert_message(
        conn,
        account_id="acct",
        mailbox="INBOX",
        uidvalidity=1,
        uid=uid,
        message_id=None,
        internal_date=f"{day}T09:00:00+09:00",
        from_addr="a@example.com",
        to_addr="b@example.com",
        subject=f"mail-{uid}",
        raw_eml_path="raw.eml",
        body_html_path=None,
        body_text_path=None,
        rendered_html_path=None,
    )
    set_analysis(
        conn,
        message_fk=fk,
        summary=summary,
        tags=[],
        topics=[],
        personal=False,
    )


def test_sync_dates_are_summarized_once(monkeypatch):
    init_db(app_db_path())
    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="sync-1", kind="sync")
        repo.add_event(
            conn,
            job_id="sync-1",
            level="info",
            text=format_overview_dates_event(["2026-04-17", "2026-04-16", "not-a-day"]),
        )
        _seed_mail(conn, uid=1, day="2026-04-16", summary="- 첫 메일")
        _seed_mail(conn, uid=2, day="2026-04-17", summary="- 둘째 메일")
        _seed_mail(conn, uid=3, day="2026-04-17", summary=SUMMARY_LLM_CALL_FAILED)
        conn.commit()
        assert overview_dates_for_sync_job(conn, "sync-1") == [
            "2026-04-16",
            "2026-04-17",
        ]
        dates = overview_dates_for_sync_job(conn, "sync-1")

    calls: list[tuple[str, list[str]]] = []

    def _synth(provider, *, day, summaries, user_profile=None):
        calls.append((day, list(summaries)))
        return f"- {day}"

    import webmail_summary.jobs.tasks_refresh_overviews as mod

    monkeypatch.setattr(mod, "synthesize_daily_overview", _synth)
    monkeypatch.setattr(mod, "get_llm_provider", lambda settings: object())

    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="job-refresh", kind="refresh-overviews")
        repo.create_job(conn, job_id="job-again", kind="refresh-overviews")

    refresh_overviews_task(date_keys=dates, force_refresh=True)(
        "job-refresh", threading.Event()
    )
    assert [day for day, _sums in calls] == ["2026-04-16", "2026-04-17"]
    april_17 = [sums for day, sums in calls if day == "2026-04-17"][0]
    assert april_17 == ["- 둘째 메일"]

    # The undated follow-up that used to run after every sync must not
    # call the model again for days that were just written.
    refresh_overviews_task()("job-again", threading.Event())
    assert [day for day, _sums in calls] == ["2026-04-16", "2026-04-17"]


def test_runner_queues_recorded_dates_and_not_a_second_job(monkeypatch):
    init_db(app_db_path())
    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="sync-1", kind="sync")
        repo.add_event(
            conn,
            job_id="sync-1",
            level="info",
            text=format_overview_dates_event(["2026-04-16"]),
        )

    seen: dict = {}

    def _task(date_keys=None, force_refresh=False):
        seen["dates"] = list(date_keys or [])
        seen["force"] = force_refresh

        def run(job_id, cancel):
            return None

        return run

    import webmail_summary.jobs.tasks_refresh_overviews as mod

    monkeypatch.setattr(mod, "refresh_overviews_task", _task)
    runner = JobRunner()
    job_id = runner.schedule_overview_refresh("sync-1")
    assert job_id
    assert seen == {"dates": ["2026-04-16"], "force": True}

    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="refresh-busy", kind="refresh-overviews")
    assert runner.schedule_overview_refresh("sync-1") is None


def test_daily_overview_drops_korean_fallback_without_calling_model():
    class _Boom(LlmProvider):
        def summarize(self, *, subject, body, multimodal_inputs=None):
            raise AssertionError(body)

    text = synthesize_daily_overview(
        _Boom(),
        day="2026-04-16",
        summaries=[SUMMARY_LLM_CALL_FAILED, "(LLM 응답 timeout)"],
    )
    assert text == ""
