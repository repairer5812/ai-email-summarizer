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
    second = runner.schedule_overview_refresh("sync-1")
    assert second
    assert second != job_id


class _ImmediateProc:
    def __init__(self, rc: int) -> None:
        self.rc = rc
        self.pid = 4242

    def wait(self, timeout=None):
        return self.rc

    def poll(self):
        return self.rc

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


def _wait_for(predicate, timeout: float = 3.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return predicate()


def _run_sync_until_refresh(monkeypatch, *, rc: int, status: str, day: str):
    """Finish one sync worker with a chosen exit code and job status."""
    import webmail_summary.jobs.runner as runner_mod
    import webmail_summary.jobs.tasks_refresh_overviews as ov

    seen: dict = {}

    def _task(date_keys=None, force_refresh=False):
        seen["dates"] = list(date_keys or [])
        seen["force"] = force_refresh

        def run(job_id, cancel):
            return None

        return run

    def _popen(cmd, **kwargs):
        job_id = cmd[cmd.index("--job-id") + 1]
        with open_db(app_db_path()) as conn:
            repo.add_event(
                conn,
                job_id=job_id,
                level="info",
                text=format_overview_dates_event([day]),
            )
            repo.set_job_status(conn, job_id=job_id, status=status)
        return _ImmediateProc(rc)

    monkeypatch.setattr(ov, "refresh_overviews_task", _task)
    monkeypatch.setattr(runner_mod.subprocess, "Popen", _popen)
    runner = JobRunner()
    sync_id = runner.enqueue(kind="sync", fn=lambda job_id, cancel: None)
    queued = _wait_for(lambda: seen.get("dates"))
    return sync_id, queued, seen


def test_sync_dates_refresh_while_manual_overview_is_queued(monkeypatch):
    init_db(app_db_path())
    with open_db(app_db_path()) as conn:
        repo.create_job(conn, job_id="manual-refresh", kind="refresh-overviews")
        repo.create_job(conn, job_id="sync-1", kind="sync")
        repo.add_event(
            conn,
            job_id="sync-1",
            level="info",
            text=format_overview_dates_event(["2026-04-18"]),
        )

    seen: dict = {}

    def _task(date_keys=None, force_refresh=False):
        seen.setdefault("calls", []).append(list(date_keys or []))

        def run(job_id, cancel):
            return None

        return run

    import webmail_summary.jobs.tasks_refresh_overviews as ov

    monkeypatch.setattr(ov, "refresh_overviews_task", _task)
    job_id = JobRunner().schedule_overview_refresh("sync-1")
    assert job_id
    assert job_id != "manual-refresh"
    assert seen["calls"] == [["2026-04-18"]]


def test_cancelled_sync_still_refreshes_exported_dates(monkeypatch):
    init_db(app_db_path())
    _sync_id, queued, seen = _run_sync_until_refresh(
        monkeypatch, rc=1, status="cancelled", day="2026-04-19"
    )
    assert queued == ["2026-04-19"]
    assert seen["force"] is True


def test_succeeded_sync_refreshes_when_worker_exit_is_nonzero(monkeypatch):
    init_db(app_db_path())
    _sync_id, queued, seen = _run_sync_until_refresh(
        monkeypatch, rc=-9, status="succeeded", day="2026-04-20"
    )
    assert queued == ["2026-04-20"]
    assert seen["force"] is True


def test_daily_overview_drops_korean_fallback_without_calling_model():
    class _Boom:
        def summarize(self, *, subject, body, multimodal_inputs=None):
            raise AssertionError(body)

    text = synthesize_daily_overview(
        _Boom(),
        day="2026-04-16",
        summaries=[SUMMARY_LLM_CALL_FAILED, "(LLM 응답 timeout)"],
    )
    assert text == ""
