"""Characterization tests for resummarize_day_task.

They pin what one resummarize run does today (targets, LLM inputs, DB rows,
job progress and events, Obsidian note updates including stale topics) so
the task can be split into smaller functions safely. The LLM, exporters and
overview refresh are fakes.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from webmail_summary.index.db import get_conn, init_db
from webmail_summary.index.mail_repo import set_analysis, upsert_message
from webmail_summary.jobs import repo
from webmail_summary.jobs import tasks_resummarize as mod
from webmail_summary.llm.base import LlmResult
from webmail_summary.llm.provider import LlmNotReady


class _Provider:
    tier = "standard"


class _World:
    def __init__(self, tmp_path: Path, monkeypatch, *, settings=None, provider=None):
        self.data_dir = tmp_path / "WebmailSummary"
        self.db_path = self.data_dir / "db.sqlite3"
        self.archive_root = tmp_path / "archive"
        self.vault_root = tmp_path / "vault"
        self.vault_root.mkdir(parents=True)
        self.llm_calls: list[dict] = []
        self.llm_script: dict[str, object] = {}
        self.email_exports: list[dict] = []
        self.daily_exports: list[dict] = []
        self.topic_exports: list[dict] = []
        self.refreshed: list[list[str]] = []
        self.progress: list[tuple[float, float, str]] = []
        self.cancel = threading.Event()
        self.cancel_on_progress_subject: str | None = None
        self.settings = settings or SimpleNamespace(
            obsidian_root=str(self.vault_root),
            sender_filter="fallback@example.com",
            cloud_provider="",
            openrouter_model="",
            cloud_multimodal_enabled=False,
            user_roles=["pm"],
            user_interests="mail",
        )
        provider = provider or _Provider()

        init_db(self.db_path)
        conn = get_conn(self.db_path)
        try:
            repo.create_job(conn, job_id="job-1", kind="resummarize-day")
        finally:
            conn.close()

        world = self

        def fake_summarize(
            _provider,
            *,
            subject,
            body,
            on_detail,
            on_progress,
            user_profile,
            multimodal_inputs=None,
        ):
            world.llm_calls.append(
                {
                    "subject": subject,
                    "body": body,
                    "user_profile": user_profile,
                    "multimodal_inputs": multimodal_inputs,
                }
            )
            on_detail({"type": "chunk", "subject": subject})
            if world.cancel_on_progress_subject == subject:
                world.cancel.set()
            on_progress(0.5)
            outcome = world.llm_script.get(subject)
            if isinstance(outcome, BaseException):
                raise outcome
            return LlmResult(
                summary=f"- new summary of {subject}",
                tags=[f"tag-{subject}"],
                backlinks=[f"topic-{subject}"],
                personal=subject.endswith("p"),
            )

        def fake_export_email_note(*, vault_root, inp):
            world.email_exports.append(
                {
                    "message_key": inp.message_key,
                    "date": inp.date.isoformat(),
                    "sender": inp.sender,
                    "subject": inp.subject,
                    "summary": inp.summary,
                    "tags": list(inp.tags),
                    "topics": list(inp.topics),
                    "archive_dir": Path(inp.archive_dir).name,
                }
            )
            note = (
                Path(vault_root)
                / "Mail"
                / f"{inp.date:%Y-%m}"
                / mod.email_note_filename(inp.date, inp.subject, inp.message_key)
            )
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(inp.summary, encoding="utf-8")
            return note

        def fake_export_daily_note(*, vault_root, date, message_notes, daily_summary):
            world.daily_exports.append(
                {
                    "date": date.isoformat(),
                    "notes": [Path(p).name for p in message_notes],
                    "daily_summary": daily_summary,
                }
            )
            return Path(vault_root) / "Daily" / f"{date:%Y-%m-%d}.md"

        def fake_export_topic_note(*, vault_root, topic, message_notes, replace):
            world.topic_exports.append(
                {
                    "topic": topic,
                    "notes": sorted(Path(p).name for p in message_notes),
                    "replace": replace,
                }
            )
            return Path(vault_root) / "Topic" / f"{topic}.md"

        def fake_refresh(*, db_path, provider, settings, date_keys, force_refresh, job_id):
            world.refreshed.append(list(date_keys))
            return list(date_keys)

        original_update_progress = repo.update_progress

        def capture_progress(conn, *, job_id, current, total, message):
            world.progress.append((round(float(current), 4), float(total), str(message)))
            return original_update_progress(
                conn, job_id=job_id, current=current, total=total, message=message
            )

        monkeypatch.setattr(mod, "load_settings", lambda conn: world.settings)
        monkeypatch.setattr(mod, "get_llm_provider", lambda s: provider)
        monkeypatch.setattr(mod, "summarize_email_long_aware", fake_summarize)
        monkeypatch.setattr(mod, "export_email_note", fake_export_email_note)
        monkeypatch.setattr(mod, "export_daily_note", fake_export_daily_note)
        monkeypatch.setattr(mod, "export_topic_note", fake_export_topic_note)
        monkeypatch.setattr(mod, "refresh_overviews_for_dates", fake_refresh)
        monkeypatch.setattr(repo, "update_progress", capture_progress)

    def seed(self, *, uid: int, day: str, subject: str, summary: str, topics=(), html=False, from_addr="sender@example.com") -> int:
        msg_dir = self.archive_root / f"msg-{uid}"
        msg_dir.mkdir(parents=True, exist_ok=True)
        text_path = None
        html_path = None
        if html:
            html_path = msg_dir / "body.html"
            html_path.write_text(f"<p>html body of {subject}</p>", encoding="utf-8")
        else:
            text_path = msg_dir / "body.txt"
            text_path.write_text(f"text body of {subject}", encoding="utf-8")
        conn = get_conn(self.db_path)
        try:
            fk = upsert_message(
                conn,
                account_id="acct",
                mailbox="INBOX",
                uidvalidity=1,
                uid=uid,
                message_id=f"<{uid}@example.com>",
                internal_date=f"{day}T09:{uid:02d}:00+09:00",
                from_addr=from_addr,
                to_addr="me@example.com",
                subject=subject,
                raw_eml_path=str(msg_dir / "raw.eml"),
                body_html_path=str(html_path) if html_path else None,
                body_text_path=str(text_path) if text_path else None,
                rendered_html_path=None,
            )
            set_analysis(
                conn,
                message_fk=fk,
                summary=summary,
                tags=[],
                topics=list(topics),
                personal=False,
                summarize_ms=100,
            )
            conn.commit()
        finally:
            conn.close()
        return fk

    def run(self, **kwargs) -> None:
        mod.resummarize_day_task(**kwargs)("job-1", self.cancel)

    def events(self) -> list[tuple[str, str]]:
        conn = get_conn(self.db_path)
        try:
            rows = conn.execute(
                "SELECT level, text FROM job_events WHERE job_id = ? ORDER BY id",
                ("job-1",),
            ).fetchall()
        finally:
            conn.close()
        return [(str(r[0]), str(r[1])) for r in rows]

    def summaries(self) -> dict[str, tuple]:
        conn = get_conn(self.db_path)
        try:
            rows = conn.execute(
                "SELECT subject, summary, tags_json, topics_json, personal FROM messages ORDER BY uid"
            ).fetchall()
        finally:
            conn.close()
        return {
            str(r[0]): (str(r[1]), json.loads(r[2]), json.loads(r[3]), int(r[4]))
            for r in rows
        }


def _detail(payload: dict) -> tuple[str, str]:
    return ("detail", json.dumps(payload, ensure_ascii=True))


def test_resummarize_single_day_all_messages_updates_notes_and_topics(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)
    id1 = world.seed(uid=1, day="2026-04-16", subject="alpha", summary="- old alpha", topics=["stale"])
    id2 = world.seed(uid=2, day="2026-04-16", subject="betap", summary="(no summary)", html=True, from_addr="")
    world.seed(uid=3, day="2026-04-17", subject="other day", summary="- untouched")
    stale_topic_file = world.vault_root / "Topic" / "stale.md"
    stale_topic_file.parent.mkdir(parents=True)
    stale_topic_file.write_text("old", encoding="utf-8")

    world.run(date_key="2026-04-16", only_failed=False)

    assert world.llm_calls == [
        {
            "subject": "alpha",
            "body": "text body of alpha",
            "user_profile": {"roles": ["pm"], "interests": "mail"},
            "multimodal_inputs": None,
        },
        {
            "subject": "betap",
            "body": "html body of betap",
            "user_profile": {"roles": ["pm"], "interests": "mail"},
            "multimodal_inputs": None,
        },
    ]
    assert world.progress == [
        (0.0, 2.0, "[2026-04-16] 날짜별 다시 요약 준비 중"),
        (0.01, 2.0, "[2026-04-16] 다시 요약 중 alpha (1/2)"),
        (0.05, 2.0, "[2026-04-16] LLM 호출 중 alpha (1/2)"),
        (0.5, 2.0, "[2026-04-16] 다시 요약 중 alpha (1/2)"),
        (1.01, 2.0, "[2026-04-16] 다시 요약 중 betap (2/2)"),
        (1.05, 2.0, "[2026-04-16] LLM 호출 중 betap (2/2)"),
        (1.5, 2.0, "[2026-04-16] 다시 요약 중 betap (2/2)"),
        (2.0, 2.0, "[2026-04-16] 다시 요약 완료"),
    ]
    events = world.events()
    llm_done = [e for e in events if e[1].startswith("LLM 완료: ")]
    assert len(llm_done) == 2 and all(level == "info" for level, _ in llm_done)
    assert [e for e in events if not e[1].startswith("LLM 완료: ")] == [
        ("info", "llm_provider=_Provider"),
        ("info", "resummarize days=2026-04-16 targets=2"),
        ("info", "item 1/2: alpha"),
        _detail({"type": "email", "message_id": id1, "index": 1, "total": 2, "subject": "alpha"}),
        _detail({"type": "stage", "stage": "read"}),
        _detail({"type": "stage", "stage": "llm"}),
        _detail({"type": "chunk", "subject": "alpha"}),
        _detail({"type": "stage", "stage": "save"}),
        ("message_updated", json.dumps({"message_id": id1, "summary": "- new summary of alpha"}, ensure_ascii=True)),
        _detail({"type": "stage", "stage": "export"}),
        ("info", "item 2/2: betap"),
        _detail({"type": "email", "message_id": id2, "index": 2, "total": 2, "subject": "betap"}),
        _detail({"type": "stage", "stage": "read"}),
        _detail({"type": "stage", "stage": "llm"}),
        _detail({"type": "chunk", "subject": "betap"}),
        _detail({"type": "stage", "stage": "save"}),
        ("message_updated", json.dumps({"message_id": id2, "summary": "- new summary of betap"}, ensure_ascii=True)),
        _detail({"type": "stage", "stage": "export"}),
    ]
    assert world.summaries() == {
        "alpha": ("- new summary of alpha", ["tag-alpha"], ["topic-alpha"], 0),
        "betap": ("- new summary of betap", ["tag-betap"], ["topic-betap"], 1),
        "other day": ("- untouched", [], [], 0),
    }
    assert world.email_exports == [
        {
            "message_key": "acct-1-1",
            "date": "2026-04-16",
            "sender": "sender@example.com",
            "subject": "alpha",
            "summary": "- new summary of alpha",
            "tags": ["tag-alpha"],
            "topics": ["topic-alpha"],
            "archive_dir": "msg-1",
        },
        {
            "message_key": "acct-1-2",
            "date": "2026-04-16",
            "sender": "fallback@example.com",
            "subject": "betap",
            "summary": "- new summary of betap",
            "tags": ["tag-betap"],
            "topics": ["topic-betap"],
            "archive_dir": "msg-2",
        },
    ]
    assert world.daily_exports == [
        {
            "date": "2026-04-16",
            "notes": [
                "2026-04-16 - alpha (acct-1-1).md",
                "2026-04-16 - betap (acct-1-2).md",
            ],
            "daily_summary": "- 2026-04-16 - alpha (acct-1-1)\n- 2026-04-16 - betap (acct-1-2)",
        }
    ]
    assert world.refreshed == [["2026-04-16"]]
    assert world.topic_exports == [
        {"topic": "topic-alpha", "notes": ["2026-04-16 - alpha (acct-1-1).md"], "replace": True},
        {"topic": "topic-betap", "notes": ["2026-04-16 - betap (acct-1-2).md"], "replace": True},
    ]
    assert not stale_topic_file.exists()


def test_resummarize_only_failed_saves_unavailable_when_llm_raises(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="good", summary="- fine")
    world.seed(uid=2, day="2026-04-16", subject="broken", summary="(LLM timeout)")
    world.llm_script["broken"] = RuntimeError("engine died")

    world.run(date_key="2026-04-16", only_failed=True)

    assert [c["subject"] for c in world.llm_calls] == ["broken"]
    assert ("warn", "LLM exception: engine died") in world.events()
    assert world.summaries()["broken"] == ("(LLM unavailable)", [], [], 0)
    assert world.summaries()["good"] == ("- fine", [], [], 0)
    assert [e["summary"] for e in world.email_exports] == ["(LLM unavailable)"]
    assert world.refreshed == [["2026-04-16"]]
    assert world.progress[-1] == (1.0, 1.0, "[2026-04-16] 다시 요약 완료")


def test_resummarize_message_ids_scope_ignores_failure_filter(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="first", summary="- fine")
    id2 = world.seed(uid=2, day="2026-04-16", subject="second", summary="- fine too")

    world.run(date_key="2026-04-16", only_failed=True, message_ids=[id2])

    assert [c["subject"] for c in world.llm_calls] == ["second"]
    assert ("info", "resummarize days=2026-04-16 targets=1") in world.events()

    with pytest.raises(RuntimeError, match="message_ids require exactly one date"):
        world.run(date_keys=["2026-04-16", "2026-04-17"], message_ids=[id2])
    with pytest.raises(RuntimeError, match="date_key required"):
        world.run(date_key="")


def test_resummarize_cancel_during_llm_stops_without_saving(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="first", summary="(no summary)")
    world.seed(uid=2, day="2026-04-16", subject="second", summary="(no summary)")
    world.cancel_on_progress_subject = "first"

    world.run(date_key="2026-04-16", only_failed=True)

    assert [c["subject"] for c in world.llm_calls] == ["first"]
    assert world.summaries()["first"][0] == "(no summary)"
    assert world.email_exports == []
    assert world.refreshed == []
    assert world.progress[-1] == (0.0, 2.0, "[2026-04-16] 다시 요약 취소됨")
    assert world.events()[-1] == ("info", "cancelled")


def test_resummarize_without_targets_reports_empty(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="good", summary="- fine")

    world.run(date_key="2026-04-16", only_failed=True)

    assert world.llm_calls == []
    assert world.events()[-1] == ("info", "no targets")
    assert world.progress[-1] == (1.0, 1.0, "[2026-04-16] 다시 요약 대상 없음")


def test_resummarize_provider_not_ready_fails_job(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch)

    def _not_ready(_settings):
        raise LlmNotReady("Local model not installed")

    monkeypatch.setattr(mod, "get_llm_provider", _not_ready)
    with pytest.raises(LlmNotReady):
        world.run(date_key="2026-04-16")
    assert world.events() == [("error", "Local model not installed")]
    conn = get_conn(world.db_path)
    try:
        job = repo.get_job(conn, "job-1")
    finally:
        conn.close()
    assert job is not None and job.status == "failed"


class _VisionProvider:
    tier = "cloud"

    def supports_multimodal_inputs(self) -> bool:
        return True


def _seed_attachment(world: _World, *, message_fk: int, uid: int) -> None:
    from webmail_summary.index.mail_repo import replace_attachments

    msg_dir = world.archive_root / f"msg-{uid}"
    (msg_dir / "attachments").mkdir(parents=True, exist_ok=True)
    (msg_dir / "attachments" / "chart.png").write_bytes(b"0" * 4096)
    conn = get_conn(world.db_path)
    try:
        replace_attachments(
            conn,
            message_fk=message_fk,
            items=[
                {
                    "filename": "chart.png",
                    "mime_type": "image/png",
                    "size_bytes": 4096,
                    "rel_path": "attachments/chart.png",
                    "content_id": None,
                    "is_inline": False,
                }
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_resummarize_passes_saved_images_when_multimodal_is_on(tmp_path, monkeypatch, enabled):
    settings = SimpleNamespace(
        obsidian_root=str(tmp_path / "vault"),
        sender_filter="",
        cloud_provider="openai",
        openrouter_model="gpt-4o-mini",
        cloud_multimodal_enabled=enabled,
        user_roles=[],
        user_interests="",
    )
    world = _World(tmp_path, monkeypatch, settings=settings, provider=_VisionProvider())
    fk = world.seed(uid=1, day="2026-04-16", subject="chart mail", summary="(no summary)")
    _seed_attachment(world, message_fk=fk, uid=1)

    world.run(date_key="2026-04-16")

    inputs = world.llm_calls[0]["multimodal_inputs"]
    if enabled:
        assert [(Path(x.path).name, x.mime_type, x.detail, x.source) for x in inputs] == [
            ("chart.png", "image/png", "low", "attachment")
        ]
    else:
        assert inputs is None


def test_resummarize_timeout_saves_placeholder_and_stops_local_server(tmp_path, monkeypatch):
    import webmail_summary.llm.llamacpp_server as llamacpp_server

    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="slow", summary="(no summary)")
    release = threading.Event()
    stops: list[bool] = []

    def _slow_summarize(_provider, **kwargs):
        release.wait(5.0)
        return LlmResult(summary="late", tags=[], backlinks=[], personal=False)

    monkeypatch.setattr(mod, "summarize_email_long_aware", _slow_summarize)
    monkeypatch.setattr(mod, "llm_timeout_seconds", lambda provider: 0.2)
    monkeypatch.setattr(llamacpp_server, "stop_server", lambda force=False: stops.append(force))
    try:
        world.run(date_key="2026-04-16")
    finally:
        release.set()

    assert ("warn", "LLM timeout: 0s (item 1/1)") in world.events()
    assert stops == [True]
    assert world.summaries()["slow"][0] == "(LLM timeout)"
    assert world.progress[-1] == (1.0, 1.0, "[2026-04-16] 다시 요약 완료")


def test_resummarize_and_sync_share_the_heartbeat_cadence(tmp_path, monkeypatch):
    from webmail_summary.jobs import llm_call

    monkeypatch.setattr(llm_call, "HEARTBEAT_INTERVAL_S", 0.05)
    world = _World(tmp_path, monkeypatch)
    world.seed(uid=1, day="2026-04-16", subject="long", summary="(no summary)")

    def _long_summarize(_provider, *, on_progress, **kwargs):
        time.sleep(0.4)
        return LlmResult(summary="- done", tags=[], backlinks=[], personal=False)

    monkeypatch.setattr(mod, "summarize_email_long_aware", _long_summarize)
    world.run(date_key="2026-04-16")

    beats = [m for _c, _t, m in world.progress if "(경과 00:00)" in m]
    assert beats and all(m == "[2026-04-16] LLM 호출 중 long (1/1) (경과 00:00)" for m in beats)
