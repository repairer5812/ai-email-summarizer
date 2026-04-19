from __future__ import annotations

from webmail_summary.api.routes_jobs import _parse_last_event_id


def test_parse_last_event_id_accepts_positive_integer():
    assert _parse_last_event_id("42") == 42


def test_parse_last_event_id_clamps_negative_value():
    assert _parse_last_event_id("-7") == 0


def test_parse_last_event_id_falls_back_for_invalid_value():
    assert _parse_last_event_id("not-a-number") == 0
    assert _parse_last_event_id(None) == 0
