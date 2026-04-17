from __future__ import annotations

from webmail_summary.ui.routes_setup import _compose_mail_filter_value


def test_compose_mail_filter_value_clears_when_split_fields_empty():
    out = _compose_mail_filter_value(
        sender_from_filter="",
        sender_domain_filter="",
        sender_subject_filter="",
        sender_filter_legacy="",
    )

    assert out == ""


def test_compose_mail_filter_value_normalizes_prefixed_split_inputs():
    out = _compose_mail_filter_value(
        sender_from_filter="from:alice@example.com, sender:bob@example.com",
        sender_domain_filter="domain:example.org, @vendor.co.kr",
        sender_subject_filter="subject:invoice, title:security",
        sender_filter_legacy="",
    )

    assert out == (
        "alice@example.com, bob@example.com, domain:example.org, "
        "domain:vendor.co.kr, subject:invoice, subject:security"
    )


def test_compose_mail_filter_value_preserves_legacy_for_old_clients():
    out = _compose_mail_filter_value(
        sender_from_filter="",
        sender_domain_filter="",
        sender_subject_filter="",
        sender_filter_legacy="alice@example.com, subject:invoice",
    )

    assert out == "alice@example.com, subject:invoice"
