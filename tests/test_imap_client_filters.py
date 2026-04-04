from __future__ import annotations

import datetime as dt

from webmail_summary.imap_client import (
    ImapSession,
    MailSearchFilter,
    build_mail_search_filter_value,
    parse_mail_search_filter,
)


class _FakeClient:
    def __init__(self, search_results=None, fetch_payload=None):
        self.search_calls: list[list[str]] = []
        self.fetch_calls: list[tuple[list[int], list[str]]] = []
        self._search_results = search_results or {}
        self._fetch_payload = fetch_payload or {}

    def search(self, criteria):
        crit = [str(x) for x in criteria]
        self.search_calls.append(crit)
        return list(self._search_results.get(tuple(crit), []))

    def fetch(self, uids, fields):
        uid_list = [int(x) for x in uids]
        field_list = [str(x) for x in fields]
        self.fetch_calls.append((uid_list, field_list))
        out = {}
        for uid in uid_list:
            payload = dict(self._fetch_payload.get(int(uid), {}))
            want_body = any(f in {"BODY.PEEK[]", "RFC822"} for f in field_list)
            if "FLAGS" in field_list or "INTERNALDATE" in field_list:
                out[int(uid)] = {
                    b"FLAGS": payload.get(b"FLAGS", tuple()),
                    b"INTERNALDATE": payload.get(b"INTERNALDATE"),
                }
            if want_body:
                out[int(uid)] = out.get(int(uid), {})
                out[int(uid)][b"BODY.PEEK[]"] = payload.get(
                    b"BODY.PEEK[]", b"From: sender@example.com\n\nHello"
                )
        return out


class _FakeSession(ImapSession):
    def __init__(self, fake: _FakeClient) -> None:
        super().__init__("imap.example.com", 993, "user", "pw")
        self._fake = fake

    @property
    def client(self):
        return self._fake


def _session(fake: _FakeClient) -> ImapSession:
    return _FakeSession(fake)


def test_search_uids_without_sender_filter_fetches_all_since():
    since = dt.date(2026, 4, 3)
    fake = _FakeClient(
        search_results={(("SINCE", since.strftime("%d-%b-%Y"))): [5, 2, 9]}
    )

    out = _session(fake).search_uids("", since, unseen_only=False, min_uid_exclusive=3)

    assert out == [5, 9]
    assert fake.search_calls == [["SINCE", since.strftime("%d-%b-%Y")]]


def test_search_uids_merges_multiple_plain_sender_terms_with_or_logic():
    since = dt.date(2026, 4, 3)
    fake = _FakeClient(
        search_results={
            ("UNSEEN", "SINCE", since.strftime("%d-%b-%Y"), "FROM", "a@example.com"): [
                7,
                1,
            ],
            ("UNSEEN", "SINCE", since.strftime("%d-%b-%Y"), "FROM", "@example.org"): [
                4,
                7,
            ],
        }
    )

    out = _session(fake).search_uids(
        "a@example.com, @example.org", since, unseen_only=True, min_uid_exclusive=None
    )

    assert out == [1, 4, 7]
    assert fake.search_calls == [
        ["UNSEEN", "SINCE", since.strftime("%d-%b-%Y"), "FROM", "a@example.com"],
        ["UNSEEN", "SINCE", since.strftime("%d-%b-%Y"), "FROM", "@example.org"],
    ]


def test_parse_mail_search_filter_supports_composite_tokens():
    filt = parse_mail_search_filter(
        "from:alice@example.com, domain:example.org, subject:invoice, @foo.com, bob@example.com"
    )

    assert filt.from_terms == ("alice@example.com", "@foo.com", "bob@example.com")
    assert filt.domain_terms == ("example.org",)
    assert filt.subject_terms == ("invoice",)


def test_build_mail_search_filter_value_serializes_split_fields():
    out = build_mail_search_filter_value(
        MailSearchFilter(
            from_terms=("alice@example.com", "bob@example.com"),
            domain_terms=("example.org", "@vendor.co.kr"),
            subject_terms=("invoice", "security"),
        )
    )

    assert out == (
        "alice@example.com, bob@example.com, domain:example.org, "
        "domain:vendor.co.kr, subject:invoice, subject:security"
    )


def test_parse_mail_search_filter_ignores_empty_prefixed_terms():
    filt = parse_mail_search_filter("subject:, domain: , from:")

    assert filt.from_terms == ()
    assert filt.domain_terms == ()
    assert filt.subject_terms == ()


def test_search_uids_intersects_sender_and_subject_groups():
    since = dt.date(2026, 4, 3)
    fake = _FakeClient(
        search_results={
            ("SINCE", since.strftime("%d-%b-%Y"), "FROM", "alice@example.com"): [
                1,
                2,
                5,
            ],
            ("SINCE", since.strftime("%d-%b-%Y"), "SUBJECT", "invoice"): [2, 3, 5],
        }
    )

    out = _session(fake).search_uids(
        "from:alice@example.com, subject:invoice",
        since,
        unseen_only=False,
        min_uid_exclusive=None,
    )

    assert out == [2, 5]
    assert fake.search_calls == [
        ["SINCE", since.strftime("%d-%b-%Y"), "FROM", "alice@example.com"],
        ["SINCE", since.strftime("%d-%b-%Y"), "SUBJECT", "invoice"],
    ]


def test_search_uids_normalizes_domain_prefix_to_at_form():
    since = dt.date(2026, 4, 3)
    fake = _FakeClient(
        search_results={
            ("SINCE", since.strftime("%d-%b-%Y"), "FROM", "@example.org"): [4, 7],
        }
    )

    out = _session(fake).search_uids(
        "domain:example.org",
        since,
        unseen_only=False,
        min_uid_exclusive=None,
    )

    assert out == [4, 7]
    assert fake.search_calls == [
        ["SINCE", since.strftime("%d-%b-%Y"), "FROM", "@example.org"],
    ]


def test_iter_messages_reports_fetch_progress_per_chunk():
    fake = _FakeClient(
        fetch_payload={
            1: {
                b"FLAGS": (b"\\Seen",),
                b"INTERNALDATE": dt.datetime(2026, 4, 3, 10, 0, 0),
                b"BODY.PEEK[]": b"raw-1",
            },
            2: {
                b"FLAGS": tuple(),
                b"INTERNALDATE": dt.datetime(2026, 4, 3, 10, 1, 0),
                b"BODY.PEEK[]": b"raw-2",
            },
            3: {
                b"FLAGS": tuple(),
                b"INTERNALDATE": dt.datetime(2026, 4, 3, 10, 2, 0),
                b"BODY.PEEK[]": b"raw-3",
            },
        }
    )
    progress: list[tuple[int, int]] = []

    out = list(
        _session(fake).iter_messages(
            [1, 2, 3],
            chunk_size=2,
            on_progress=lambda cur, total: progress.append((cur, total)),
        )
    )

    assert [m.uid for m in out] == [1, 2, 3]
    assert [m.rfc822 for m in out] == [b"raw-1", b"raw-2", b"raw-3"]
    assert progress == [(2, 3), (3, 3)]
