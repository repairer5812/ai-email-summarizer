"""Characterization tests for sync_mailbox_task.

They pin the observable behavior of one sync run (IMAP calls, DB rows,
job progress and events, Obsidian export calls, LLM inputs) so the task can
be split into smaller functions without changing what it does. IMAP, the
archive step, the LLM and the exporters are fakes; nothing leaves the test.
"""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from webmail_summary.archive.mime_parts import SavedAttachment
from webmail_summary.imap_client import ImapMessage
from webmail_summary.index.db import get_conn, init_db
from webmail_summary.index.mail_repo import set_seen_marked, upsert_message
from webmail_summary.jobs import repo
from webmail_summary.jobs import tasks_sync as mod
from webmail_summary.llm.base import LlmResult
from webmail_summary.llm.provider import LlmNotReady

KST = dt.timezone(dt.timedelta(hours=9))
UIDVALIDITY = 7
ACCOUNT = "me@example.com@imap.example.com"


class _LocalProvider:
    tier = "standard"

    def supports_multimodal_inputs(self) -> bool:
        return False


class CloudProvider:
    """Name matters: tasks_sync picks the concurrent path by class name."""

    tier = "cloud"

    def __init__(self, *, multimodal: bool = False) -> None:
        self._multimodal = multimodal

    def supports_multimodal_inputs(self) -> bool:
        return self._multimodal


def _raw_mail(subject: str) -> bytes:
    return (
        f"Message-ID: <{subject}@example.com>\r\n"
        "From: Sender <sender@example.com>\r\n"
        "To: me@example.com\r\n"
        f"Subject: {subject}\r\n"
        "\r\n"
        f"body of {subject}\r\n"
    ).encode("utf-8")


def _settings(vault_root: Path, **overrides) -> SimpleNamespace:
    base = dict(
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="me@example.com",
        imap_folder="INBOX",
        sender_filter="sender@example.com",
        obsidian_root=str(vault_root),
        revert_seen_after_sync=False,
        cloud_provider="openai",
        openrouter_model="gpt-4o-mini",
        cloud_multimodal_enabled=False,
        user_roles=["dev"],
        user_interests="ai",
        external_max_bytes=1024,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _World:
    """Fakes for every external dependency of sync_mailbox_task."""

    def __init__(self, tmp_path: Path, monkeypatch, *, messages, settings, provider):
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "WebmailSummary"
        self.db_path = self.data_dir / "db.sqlite3"
        self.vault_root = Path(settings.obsidian_root)
        self.messages = {int(m.uid): m for m in messages}
        self.search_result = [int(m.uid) for m in messages]
        self.imap_log: list[tuple] = []
        self.mark_seen_failures: dict[int, int] = {}
        self.llm_calls: list[dict] = []
        self.llm_script: dict[str, object] = {}
        self.attachments_by_uid: dict[int, list[tuple[str, bytes, str]]] = {}
        self.export_failures: set[str] = set()
        self.email_exports: list[dict] = []
        self.daily_exports: list[dict] = []
        self.topic_exports: list[dict] = []
        self.refreshed: list[list[str]] = []
        self.progress: list[tuple[float, float, str]] = []
        self.stop_server_calls: list[bool] = []
        self.cancel = threading.Event()
        self.cancel_after_llm_subject: str | None = None

        init_db(self.db_path)
        conn = get_conn(self.db_path)
        try:
            repo.create_job(conn, job_id="job-1", kind="sync")
        finally:
            conn.close()

        world = self

        class FakeImap:
            def __init__(self, host, port, user, password):
                world.imap_log.append(("open", host, port, user, password))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                world.imap_log.append(("close",))
                return None

            def select_folder(self, folder, readonly=False):
                world.imap_log.append(("select", folder, readonly))

            def get_uidvalidity_for(self, folder):
                return UIDVALIDITY

            def search_uids(self, sender_filter, since, *, unseen_only, min_uid_exclusive):
                world.imap_log.append(
                    ("search", sender_filter, unseen_only, min_uid_exclusive)
                )
                return list(world.search_result)

            def iter_messages(self, uids, *, chunk_size, on_progress):
                uids = [int(u) for u in uids]
                world.imap_log.append(("iter", uids, chunk_size))

                def gen():
                    if on_progress is not None:
                        on_progress(len(uids), len(uids))
                    for uid in uids:
                        yield world.messages[uid]

                return gen()

            def mark_seen(self, uid):
                left = world.mark_seen_failures.get(int(uid), 0)
                if left > 0:
                    world.mark_seen_failures[int(uid)] = left - 1
                    world.imap_log.append(("mark_seen_failed", int(uid)))
                    raise OSError("socket closed")
                world.imap_log.append(("mark_seen", int(uid)))

            def clear_seen(self, uid):
                world.imap_log.append(("clear_seen", int(uid)))

        def fake_archive_message(*, raw_rfc822, paths, external_max_bytes):
            base = Path(paths.base_dir)
            (base / "raw.eml").write_bytes(raw_rfc822)
            body = raw_rfc822.split(b"\r\n\r\n", 1)[1].decode("utf-8").strip()
            (base / "body.txt").write_text(body, encoding="utf-8")
            uid = int(base.name)
            attachments = []
            for name, blob, mime in world.attachments_by_uid.get(uid, []):
                rel = f"attachments/{name}"
                (base / rel).write_bytes(blob)
                attachments.append(
                    SavedAttachment(
                        filename=name,
                        rel_path=rel,
                        mime_type=mime,
                        size_bytes=len(blob),
                        content_id=None,
                        is_inline=False,
                    )
                )
            return SimpleNamespace(
                raw_eml_path=base / "raw.eml",
                body_html_path=None,
                body_text_path=base / "body.txt",
                rendered_html_path=None,
                attachments=attachments,
                external_assets=[],
            )

        def fake_summarize(provider, *, subject, body, on_progress, user_profile, multimodal_inputs):
            world.llm_calls.append(
                {
                    "subject": subject,
                    "body": body,
                    "user_profile": user_profile,
                    "has_progress_cb": on_progress is not None,
                    "images": [
                        (Path(x.path).name, x.mime_type, x.detail, x.source)
                        for x in (multimodal_inputs or [])
                    ]
                    if multimodal_inputs is not None
                    else None,
                }
            )
            if on_progress is not None:
                on_progress(0.5)
            if world.cancel_after_llm_subject == subject:
                world.cancel.set()
            outcome = world.llm_script.get(subject)
            if isinstance(outcome, BaseException):
                raise outcome
            if callable(outcome):
                return outcome()
            topics = [f"topic-{subject[-1]}"]
            return LlmResult(
                summary=f"- summary of {subject}",
                tags=[f"tag-{subject}"],
                backlinks=topics,
                personal=False,
            )

        def fake_export_email_note(*, vault_root, inp):
            if inp.subject in world.export_failures:
                raise OSError(f"disk full for {inp.subject}")
            world.email_exports.append(
                {
                    "message_key": inp.message_key,
                    "date": inp.date.isoformat(),
                    "sender": inp.sender,
                    "subject": inp.subject,
                    "summary": inp.summary,
                    "tags": list(inp.tags),
                    "topics": list(inp.topics),
                    "archive_dir": Path(inp.archive_dir).relative_to(world.data_dir).as_posix(),
                }
            )
            return Path(vault_root) / "Mail" / f"{inp.subject}.md"

        def fake_export_daily_note(*, vault_root, date, message_notes, daily_summary):
            world.daily_exports.append(
                {
                    "date": date.isoformat(),
                    "notes": [Path(p).name for p in message_notes],
                    "daily_summary": daily_summary,
                }
            )
            return Path(vault_root) / "Daily" / f"{date:%Y-%m-%d}.md"

        def fake_export_topic_note(*, vault_root, topic, message_notes):
            world.topic_exports.append(
                {"topic": topic, "notes": [Path(p).name for p in message_notes]}
            )
            return Path(vault_root) / "Topic" / f"{topic}.md"

        def fake_refresh(*, db_path, provider, settings, date_keys, force_refresh, job_id):
            world.refreshed.append(sorted(date_keys))
            return sorted(date_keys)

        original_update_progress = repo.update_progress

        def capture_progress(conn, *, job_id, current, total, message):
            world.progress.append((round(float(current), 4), float(total), str(message)))
            return original_update_progress(
                conn, job_id=job_id, current=current, total=total, message=message
            )

        import webmail_summary.llm.llamacpp_server as llamacpp_server

        monkeypatch.setattr(mod, "ImapSession", FakeImap)
        monkeypatch.setattr(mod.keyring, "get_password", lambda service, user: "pw")
        monkeypatch.setattr(mod, "load_settings", lambda conn: settings)
        monkeypatch.setattr(mod, "get_llm_provider", lambda s: provider)
        monkeypatch.setattr(mod, "archive_message", fake_archive_message)
        monkeypatch.setattr(mod, "summarize_email_long_aware", fake_summarize)
        monkeypatch.setattr(mod, "export_email_note", fake_export_email_note)
        monkeypatch.setattr(mod, "export_daily_note", fake_export_daily_note)
        monkeypatch.setattr(mod, "export_topic_note", fake_export_topic_note)
        monkeypatch.setattr(mod, "refresh_overviews_for_dates", fake_refresh)
        monkeypatch.setattr(repo, "update_progress", capture_progress)
        monkeypatch.setattr(
            llamacpp_server,
            "stop_server",
            lambda force=False: world.stop_server_calls.append(bool(force)),
        )

    def run(self) -> None:
        mod.sync_mailbox_task()("job-1", self.cancel)

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

    def rows(self) -> list[dict]:
        conn = get_conn(self.db_path)
        try:
            rows = conn.execute(
                "SELECT uid, subject, summary, tags_json, topics_json, personal, "
                "summarize_ms IS NOT NULL AS has_ms, exported_at IS NOT NULL AS exported, "
                "seen_marked_at IS NOT NULL AS seen, internal_date, from_addr "
                "FROM messages ORDER BY uid"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]


def _msg(uid: int, subject: str, *, day: int = 16, seen: bool = False) -> ImapMessage:
    return ImapMessage(
        uid=uid,
        rfc822=_raw_mail(subject),
        internaldate=dt.datetime(2026, 4, day, 9, uid, tzinfo=KST),
        flags=(b"\\Seen",) if seen else (),
    )


def test_sync_serial_path_archives_summarizes_exports_and_marks(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[
            _msg(1, "mail-1"),
            _msg(2, "mail-2", day=17, seen=True),
            _msg(3, "mail-3", day=17),
        ],
        settings=_settings(vault, revert_seen_after_sync=True),
        provider=_LocalProvider(),
    )
    world.mark_seen_failures[3] = 1  # first attempt fails, reconnect succeeds

    world.run()

    assert world.imap_log == [
        ("open", "imap.example.com", 993, "me@example.com", "pw"),
        ("select", "INBOX", False),
        ("search", "sender@example.com", False, None),
        ("iter", [1, 2, 3], 20),
        ("mark_seen", 1),
        ("mark_seen", 2),
        ("mark_seen_failed", 3),
        ("open", "imap.example.com", 993, "me@example.com", "pw"),
        ("select", "INBOX", False),
        ("mark_seen", 3),
        ("close",),
        ("clear_seen", 1),
        ("clear_seen", 3),
        ("close",),
    ]
    assert world.llm_calls == [
        {
            "subject": f"mail-{i}",
            "body": f"body of mail-{i}",
            "user_profile": {"roles": ["dev"], "interests": "ai"},
            "has_progress_cb": True,
            "images": None,
        }
        for i in (1, 2, 3)
    ]
    assert world.progress == [
        (0.0, 3.0, "동기화 준비 중"),
        (0.0, 3.0, "메일 가져오는 중 (3/3)"),
        (0.01, 3.0, "[2026-04-16] 백업 중: mail-1"),
        (0.01, 3.0, "[2026-04-16] 저장 중: mail-1"),
        (0.01, 3.0, "[2026-04-16] 요약 중: mail-1"),
        (0.5, 3.0, "[2026-04-16] 요약 중: mail-1 (1/3)"),
        (0.01, 3.0, "[2026-04-16] Obsidian 내보내기 중: mail-1"),
        (0.01, 3.0, "[2026-04-16] 읽음 처리 중: mail-1"),
        (1.01, 3.0, "[2026-04-17] 백업 중: mail-2"),
        (1.01, 3.0, "[2026-04-17] 저장 중: mail-2"),
        (1.01, 3.0, "[2026-04-17] 요약 중: mail-2"),
        (1.5, 3.0, "[2026-04-17] 요약 중: mail-2 (2/3)"),
        (1.01, 3.0, "[2026-04-17] Obsidian 내보내기 중: mail-2"),
        (1.01, 3.0, "[2026-04-17] 읽음 처리 중: mail-2"),
        (2.01, 3.0, "[2026-04-17] 백업 중: mail-3"),
        (2.01, 3.0, "[2026-04-17] 저장 중: mail-3"),
        (2.01, 3.0, "[2026-04-17] 요약 중: mail-3"),
        (2.5, 3.0, "[2026-04-17] 요약 중: mail-3 (3/3)"),
        (2.01, 3.0, "[2026-04-17] Obsidian 내보내기 중: mail-3"),
        (2.01, 3.0, "[2026-04-17] 읽음 처리 중: mail-3"),
    ]
    assert world.events() == [
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("info", "daily_overview refreshed: 2026-04-16, 2026-04-17"),
    ]
    assert world.email_exports == [
        {
            "message_key": f"{ACCOUNT}-{UIDVALIDITY}-{i}",
            "date": day,
            "sender": "Sender <sender@example.com>",
            "subject": f"mail-{i}",
            "summary": f"- summary of mail-{i}",
            "tags": [f"tag-mail-{i}"],
            "topics": [f"topic-{i}"],
            "archive_dir": f"data/messages/me-example.com-imap.example.com/INBOX/{UIDVALIDITY}/{i}",
        }
        for i, day in ((1, "2026-04-16"), (2, "2026-04-17"), (3, "2026-04-17"))
    ]
    assert world.daily_exports == [
        {"date": "2026-04-16", "notes": ["mail-1.md"], "daily_summary": "- mail-1"},
        {
            "date": "2026-04-17",
            "notes": ["mail-2.md", "mail-3.md"],
            "daily_summary": "- mail-2\n- mail-3",
        },
    ]
    assert world.topic_exports == [
        {"topic": "topic-1", "notes": ["mail-1.md"]},
        {"topic": "topic-2", "notes": ["mail-2.md"]},
        {"topic": "topic-3", "notes": ["mail-3.md"]},
    ]
    assert world.refreshed == [["2026-04-16", "2026-04-17"]]
    rows = world.rows()
    assert [(r["uid"], r["summary"], r["exported"], r["seen"]) for r in rows] == [
        (1, "- summary of mail-1", 1, 1),
        (2, "- summary of mail-2", 1, 1),
        (3, "- summary of mail-3", 1, 1),
    ]
    assert [r["internal_date"] for r in rows] == [
        "2026-04-16T09:01:00+09:00",
        "2026-04-17T09:02:00+09:00",
        "2026-04-17T09:03:00+09:00",
    ]
    assert all(r["has_ms"] for r in rows)
    assert world.stop_server_calls == []


def test_sync_serial_path_keeps_failed_llm_and_export_mail_for_retry(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(4, "mail-4"), _msg(5, "mail-5"), _msg(6, "mail-6")],
        settings=_settings(vault),
        provider=_LocalProvider(),
    )
    # Seed an earlier, fully processed message so the UID watermark is 3,
    # and an incomplete one (uid 2) that must be retried first.
    conn = get_conn(world.db_path)
    try:
        for uid, done in ((2, False), (3, True)):
            fk = upsert_message(
                conn,
                account_id=ACCOUNT,
                mailbox="INBOX",
                uidvalidity=UIDVALIDITY,
                uid=uid,
                message_id=None,
                internal_date="2026-04-15T09:00:00+09:00",
                from_addr="sender@example.com",
                to_addr="me@example.com",
                subject=f"old-{uid}",
                raw_eml_path="x",
                body_html_path=None,
                body_text_path=None,
                rendered_html_path=None,
            )
            if done:
                set_seen_marked(conn, message_fk=fk)
        conn.commit()
    finally:
        conn.close()
    world.messages[2] = _msg(2, "mail-2", day=15)
    # The server applies the UID watermark (UID > 3).
    world.search_result = [4, 5, 6]
    world.llm_script["mail-4"] = RuntimeError("model crashed")
    world.export_failures.add("mail-5")

    world.run()

    assert ("search", "sender@example.com", False, 3) in world.imap_log
    assert ("iter", [2, 4, 5, 6], 20) in world.imap_log
    assert [c["subject"] for c in world.llm_calls] == [
        "mail-2",
        "mail-4",
        "mail-5",
        "mail-6",
    ]
    marked = [e[1] for e in world.imap_log if e[0] == "mark_seen"]
    assert marked == [2, 6]
    assert world.events() == [
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("warn", "LLM exception: model crashed"),
        ("warn", "LLM 실패 메일 (2/4): 다음 sync 때 자동 재시도합니다"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("error", "Obsidian export failed (continuing): disk full for mail-5"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
        ("info", "daily_overview refreshed: 2026-04-15, 2026-04-16"),
    ]
    assert (3.0, 4.0, "[2026-04-16] Obsidian 내보내기 실패 (계속): mail-5 (3/4)") in world.progress
    rows = {r["uid"]: r for r in world.rows()}
    assert rows[4]["summary"] == "(LLM unavailable)"
    assert rows[4]["tags_json"] == "[]" and rows[4]["topics_json"] == "[]"
    assert (rows[4]["exported"], rows[4]["seen"]) == (0, 0)
    assert rows[5]["summary"] == "- summary of mail-5"
    assert (rows[5]["exported"], rows[5]["seen"]) == (0, 0)
    assert (rows[6]["exported"], rows[6]["seen"]) == (1, 1)
    assert [d["date"] for d in world.daily_exports] == ["2026-04-15", "2026-04-16"]
    assert world.refreshed == [["2026-04-15", "2026-04-16"]]


def test_sync_concurrent_cloud_path_chunks_and_passes_images(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1"), _msg(2, "mail-2"), _msg(3, "mail-3")],
        settings=_settings(
            vault, cloud_provider="google", openrouter_model="gemini-2.5-flash",
            cloud_multimodal_enabled=True,
        ),
        provider=CloudProvider(multimodal=True),
    )
    big_png = b"\x89PNG\r\n\x1a\n" + b"0" * 4096
    world.attachments_by_uid[1] = [
        ("chart.png", big_png, "image/png"),
        ("tiny.png", b"\x89PNG", "image/png"),
    ]
    world.llm_script["mail-2"] = ValueError("bad json")

    world.run()

    # google -> chunk size 2: [1, 2] then [3]
    assert ("iter", [1, 2, 3], 20) in world.imap_log
    calls = {c["subject"]: c for c in world.llm_calls}
    assert calls["mail-1"]["images"] == [("chart.png", "image/png", "low", "attachment")]
    assert calls["mail-2"]["images"] is None
    assert all(not c["has_progress_cb"] for c in world.llm_calls)
    events = world.events()
    assert events[:3] == [
        ("info", "아카이브 시작"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
    ]
    assert ("warn", "LLM exception (ValueError): bad json") in events
    assert ("warn", "LLM 실패 메일 (2/3): 다음 sync 때 자동 재시도합니다") in events
    assert world.progress[:3] == [
        (0.0, 3.0, "동기화 준비 중"),
        (0.0, 3.0, "메일 가져오는 중 (3/3)"),
        (0.01, 3.0, "[2026-04-16] 백업 중: mail-1"),
    ]
    assert (0.01, 3.0, "[2026-04-16] 요약 중 동시 처리 (1~2/3)") in world.progress
    assert (1.0, 3.0, "[2026-04-16] 저장·읽음 처리 중 (1~2/3)") in world.progress
    assert (3.0, 3.0, "[2026-04-16] 저장·읽음 처리 중 (3~3/3)") in world.progress
    stage_msgs = [m for _c, _t, m in world.progress if "Obsidian 내보내기 중" in m]
    assert stage_msgs == []
    rows = {r["uid"]: r for r in world.rows()}
    assert rows[2]["summary"] == "(LLM 호출 실패)"
    assert (rows[2]["exported"], rows[2]["seen"]) == (0, 0)
    assert (rows[1]["exported"], rows[1]["seen"]) == (1, 1)
    assert (rows[3]["exported"], rows[3]["seen"]) == (1, 1)
    marked = [e[1] for e in world.imap_log if e[0] == "mark_seen"]
    assert marked == [1, 3]


def test_sync_serial_timeout_records_fallback_and_stops_local_server(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1")],
        settings=_settings(vault),
        provider=_LocalProvider(),
    )
    release = threading.Event()

    def _slow():
        release.wait(5.0)
        return LlmResult(summary="late", tags=[], backlinks=[], personal=False)

    world.llm_script["mail-1"] = _slow
    monkeypatch.setattr(mod, "llm_timeout_seconds", lambda provider: 0.2)
    try:
        world.run()
    finally:
        release.set()

    assert ("warn", "LLM timeout: 0s (item 1/1)") in world.events()
    assert ("warn", "LLM 실패 메일 (1/1): 다음 sync 때 자동 재시도합니다") in world.events()
    assert world.stop_server_calls == [True]
    rows = world.rows()
    assert rows[0]["summary"] == "(LLM timeout)"
    assert (rows[0]["exported"], rows[0]["seen"]) == (0, 0)


def test_sync_cancel_stops_before_next_chunk(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1"), _msg(2, "mail-2")],
        settings=_settings(vault),
        provider=_LocalProvider(),
    )
    world.cancel_after_llm_subject = "mail-1"

    world.run()

    assert [c["subject"] for c in world.llm_calls] == ["mail-1"]
    rows = world.rows()
    assert [r["uid"] for r in rows] == [1]
    # The summary is computed but phase 3 skips persisting once cancelled.
    assert rows[0]["summary"] is None
    assert world.email_exports == []
    assert world.daily_exports == []
    assert world.refreshed == []


def test_sync_requires_configuration_password_and_provider(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[],
        settings=_settings(vault, imap_host=""),
        provider=_LocalProvider(),
    )
    with pytest.raises(RuntimeError, match="not configured"):
        world.run()

    monkeypatch.setattr(mod, "load_settings", lambda conn: _settings(vault))
    monkeypatch.setattr(mod.keyring, "get_password", lambda service, user: None)
    with pytest.raises(RuntimeError, match="password not stored"):
        world.run()

    monkeypatch.setattr(mod.keyring, "get_password", lambda service, user: "pw")

    def _not_ready(_settings):
        raise LlmNotReady("Local engine not installed")

    monkeypatch.setattr(mod, "get_llm_provider", _not_ready)
    with pytest.raises(LlmNotReady):
        world.run()
    assert world.events() == [("error", "Local engine not installed")]
    conn = get_conn(world.db_path)
    try:
        job = repo.get_job(conn, "job-1")
    finally:
        conn.close()
    assert job is not None and job.status == "failed"
    assert world.imap_log == []


def test_sync_serial_heartbeat_reports_elapsed(tmp_path, monkeypatch):
    from webmail_summary.jobs import llm_call

    monkeypatch.setattr(llm_call, "HEARTBEAT_INTERVAL_S", 0.05)
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1")],
        settings=_settings(vault),
        provider=_LocalProvider(),
    )

    def _long():
        import time as _time

        _time.sleep(0.4)
        return LlmResult(summary="- done", tags=[], backlinks=["t"], personal=False)

    world.llm_script["mail-1"] = _long
    world.run()

    beats = [(c, m) for c, _t, m in world.progress if "(경과 00:00)" in m]
    # The heartbeat never moves progress backwards: on_progress already set 0.5.
    assert beats and all(
        (c, m) == (0.5, "[2026-04-16] 요약 중: mail-1 (1/1) (경과 00:00)") for c, m in beats
    )


def test_sync_concurrent_cancel_skips_persisting_the_chunk(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1"), _msg(2, "mail-2"), _msg(3, "mail-3")],
        settings=_settings(vault, cloud_provider="google"),
        provider=CloudProvider(),
    )
    world.cancel_after_llm_subject = "mail-1"

    world.run()

    rows = world.rows()
    assert [r["uid"] for r in rows] == [1, 2]
    assert all(r["summary"] is None for r in rows)
    assert world.email_exports == []
    assert world.refreshed == []
    assert [e for e in world.imap_log if e[0] == "mark_seen"] == []
    assert world.events() == [
        ("info", "아카이브 시작"),
        ("info", "아카이브 시작"),
        ("info", "요약 시작"),
    ]


def test_sync_concurrent_future_timeout_records_fallback(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    world = _World(
        tmp_path,
        monkeypatch,
        messages=[_msg(1, "mail-1"), _msg(2, "mail-2")],
        settings=_settings(vault, cloud_provider="google"),
        provider=CloudProvider(),
    )
    release = threading.Event()

    def _slow():
        release.wait(5.0)
        return LlmResult(summary="late", tags=[], backlinks=[], personal=False)

    world.llm_script["mail-1"] = _slow
    monkeypatch.setattr(mod, "llm_timeout_seconds", lambda provider: 0.2)
    # Released well after the 0.5 s cloud pacing delay plus the 0.2 s timeout.
    timer = threading.Timer(2.0, release.set)
    timer.start()
    try:
        world.run()
    finally:
        release.set()
        timer.cancel()

    events = world.events()
    assert events[3][0] == "warn"
    assert events[3][1].startswith("LLM 호출 timeout (1/2, 대기 0초): ")
    assert ("warn", "LLM 실패 메일 (1/2): 다음 sync 때 자동 재시도합니다") in events
    rows = {r["uid"]: r for r in world.rows()}
    assert rows[1]["summary"] == "(LLM timeout)"
    assert (rows[1]["exported"], rows[1]["seen"]) == (0, 0)
    assert (rows[2]["exported"], rows[2]["seen"]) == (1, 1)
