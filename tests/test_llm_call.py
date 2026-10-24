from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from webmail_summary.index.db import get_conn, init_db
from webmail_summary.index.mail_repo import (
    replace_attachments,
    replace_external_assets,
    upsert_message,
)
from webmail_summary.jobs import llm_call
from webmail_summary.llm.base import LlmResult


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("openai", "", 0.3),
        ("Anthropic", "", 0.3),
        ("openrouter", "google/gemini-2.5-flash", 0.3),
        ("google", "", 0.5),
        ("upstage", "", 0.5),
        ("", "gemini-2.5-flash", 0.5),
        ("", "", 0.4),
        (None, None, 0.4),
    ],
)
def test_cloud_base_delay_seconds_table(provider, model, expected):
    assert llm_call.cloud_base_delay_seconds(provider, model) == expected


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("cloud", 420.0), ("fast", 240.0), ("standard", 360.0), ("performance", 360.0)],
)
def test_llm_timeout_seconds_by_tier(tier, expected):
    assert llm_call.llm_timeout_seconds(SimpleNamespace(tier=tier)) == expected
    assert llm_call.llm_timeout_seconds(object()) == 360.0


def test_format_elapsed():
    assert llm_call.format_elapsed(0) == "00:00"
    assert llm_call.format_elapsed(65.9) == "01:05"
    assert llm_call.format_elapsed(-3) == "00:00"


def test_heartbeat_ticks_and_stops_promptly():
    ticks: list[float] = []
    hb = llm_call.Heartbeat(ticks.append, interval_s=0.02).start()
    deadline = time.monotonic() + 2.0
    while len(ticks) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    hb.stop()
    assert len(ticks) >= 3
    assert ticks == sorted(ticks)
    assert not hb._thread.is_alive()

    slow = llm_call.Heartbeat(ticks.append, interval_s=30.0).start()
    t0 = time.monotonic()
    slow.stop()
    assert time.monotonic() - t0 < 0.5
    assert not slow._thread.is_alive()


def test_heartbeat_survives_failing_tick_and_honours_cancel():
    calls: list[float] = []

    def _tick(elapsed):
        calls.append(elapsed)
        if len(calls) == 1:
            raise RuntimeError("db locked")

    hb = llm_call.Heartbeat(_tick, interval_s=0.02).start()
    deadline = time.monotonic() + 2.0
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    hb.stop()
    assert len(calls) >= 2

    cancel = threading.Event()
    cancel.set()
    cancelled: list[float] = []
    hb2 = llm_call.Heartbeat(cancelled.append, interval_s=0.02, cancel=cancel).start()
    hb2._thread.join(timeout=1.0)
    assert not hb2._thread.is_alive()
    assert cancelled == []


def test_heartbeat_default_interval_is_read_at_construction(monkeypatch):
    monkeypatch.setattr(llm_call, "HEARTBEAT_INTERVAL_S", 0.01)
    assert llm_call.Heartbeat(lambda _e: None)._interval_s == 0.01


def _patch_stop_server(monkeypatch) -> list[bool]:
    import webmail_summary.llm.llamacpp_server as llamacpp_server

    calls: list[bool] = []
    monkeypatch.setattr(
        llamacpp_server, "stop_server", lambda force=False: calls.append(bool(force))
    )
    return calls


def test_call_with_deadline_returns_result_and_stops_heartbeat(monkeypatch):
    stops = _patch_stop_server(monkeypatch)
    hb = llm_call.Heartbeat(lambda _e: None, interval_s=30.0)
    res = LlmResult(summary="ok", tags=[], backlinks=[], personal=False)

    outcome = llm_call.call_with_deadline(lambda: res, timeout_s=5.0, heartbeat=hb)

    assert outcome == llm_call.LlmCallOutcome(result=res, error=None, timed_out=False)
    assert not hb._thread.is_alive()
    assert stops == []


def test_call_with_deadline_captures_errors(monkeypatch):
    _patch_stop_server(monkeypatch)

    def _boom():
        raise ValueError("bad json")

    outcome = llm_call.call_with_deadline(_boom, timeout_s=5.0)
    assert outcome.result is None and outcome.timed_out is False
    assert isinstance(outcome.error, ValueError)


def test_call_with_deadline_timeout_logs_then_stops_server(monkeypatch):
    stops = _patch_stop_server(monkeypatch)
    order: list[str] = []
    release = threading.Event()
    hb = llm_call.Heartbeat(lambda _e: None, interval_s=30.0)

    def _slow():
        release.wait(5.0)
        return LlmResult(summary="late", tags=[], backlinks=[], personal=False)

    try:
        outcome = llm_call.call_with_deadline(
            _slow,
            timeout_s=0.05,
            heartbeat=hb,
            on_timeout=lambda: order.append("logged"),
        )
    finally:
        release.set()

    assert outcome == llm_call.LlmCallOutcome(result=None, error=None, timed_out=True)
    assert order == ["logged"]
    assert stops == [True]
    assert not hb._thread.is_alive()


def test_wants_multimodal_inputs():
    on = SimpleNamespace(cloud_multimodal_enabled=True)
    off = SimpleNamespace(cloud_multimodal_enabled=False)

    class _Yes:
        def supports_multimodal_inputs(self):
            return True

    class _No:
        def supports_multimodal_inputs(self):
            return False

    assert llm_call.wants_multimodal_inputs(_Yes(), on) is True
    assert llm_call.wants_multimodal_inputs(_Yes(), off) is False
    assert llm_call.wants_multimodal_inputs(_No(), on) is False
    assert llm_call.wants_multimodal_inputs(object(), on) is False
    assert llm_call.wants_multimodal_inputs(_Yes(), SimpleNamespace()) is False


def test_load_stored_multimodal_inputs_reads_saved_rows(tmp_path):
    db_path = tmp_path / "db.sqlite3"
    init_db(db_path)
    base_dir = tmp_path / "msg"
    (base_dir / "attachments").mkdir(parents=True)
    (base_dir / "external").mkdir()
    (base_dir / "attachments" / "chart.png").write_bytes(b"0" * 5000)
    (base_dir / "attachments" / "logo.png").write_bytes(b"0" * 5000)
    (base_dir / "external" / "photo.jpg").write_bytes(b"0" * 3000)
    conn = get_conn(db_path)
    try:
        fk = upsert_message(
            conn,
            account_id="a",
            mailbox="INBOX",
            uidvalidity=1,
            uid=1,
            message_id=None,
            internal_date="2026-04-16T09:00:00+09:00",
            from_addr=None,
            to_addr=None,
            subject="s",
            raw_eml_path=str(base_dir / "raw.eml"),
            body_html_path=None,
            body_text_path=None,
            rendered_html_path=None,
        )
        replace_attachments(
            conn,
            message_fk=fk,
            items=[
                {"filename": "chart.png", "mime_type": "image/png", "size_bytes": 5000,
                 "rel_path": "attachments/chart.png", "content_id": None, "is_inline": True},
                {"filename": "logo.png", "mime_type": "image/png", "size_bytes": 5000,
                 "rel_path": "attachments/logo.png", "content_id": None, "is_inline": False},
            ],
        )
        replace_external_assets(
            conn,
            message_fk=fk,
            items=[
                {"original_url": "https://example.com/p.jpg", "rel_path": "external/photo.jpg",
                 "mime_type": "image/jpeg", "size_bytes": 3000, "status": "downloaded"},
                {"original_url": "https://example.com/x.jpg", "rel_path": None,
                 "mime_type": "image/jpeg", "size_bytes": None, "status": "failed"},
            ],
        )
        conn.commit()

        selected = llm_call.load_stored_multimodal_inputs(
            conn, message_fk=fk, base_dir=base_dir
        )
    finally:
        conn.close()

    assert [(Path(p.path).name, p.mime_type, p.detail, p.source) for p in selected] == [
        ("chart.png", "image/png", "low", "inline_attachment"),
        ("photo.jpg", "image/jpeg", "low", "external_asset"),
    ]
