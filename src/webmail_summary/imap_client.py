from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from typing import Any, Iterable, Mapping, cast

from imapclient import IMAPClient


@dataclass(frozen=True)
class ImapMessage:
    uid: int
    rfc822: bytes
    internaldate: dt.datetime | None
    flags: tuple[bytes, ...]


@dataclass(frozen=True)
class MailSearchFilter:
    from_terms: tuple[str, ...] = ()
    domain_terms: tuple[str, ...] = ()
    subject_terms: tuple[str, ...] = ()


def build_mail_search_filter_value(mail_filter: MailSearchFilter) -> str:
    parts: list[str] = []
    for term in mail_filter.from_terms:
        t = str(term or "").strip()
        if t:
            parts.append(t)
    for term in mail_filter.domain_terms:
        t = str(term or "").strip().lstrip("@")
        if t:
            parts.append(f"domain:{t}")
    for term in mail_filter.subject_terms:
        t = str(term or "").strip()
        if t:
            parts.append(f"subject:{t}")
    return ", ".join(parts)


def parse_mail_search_filter(raw_value: str) -> MailSearchFilter:
    raw = str(raw_value or "").strip()
    if not raw:
        return MailSearchFilter()
    if raw.lower() in {"*", "all", "any"}:
        return MailSearchFilter()

    groups: dict[str, list[str]] = {
        "from": [],
        "domain": [],
        "subject": [],
    }

    for chunk in re.split(r"[\n,;]+", raw):
        token = chunk.strip().strip('"').strip("'")
        if not token:
            continue

        key = "from"
        value = token
        if ":" in token:
            prefix, rest = token.split(":", 1)
            prefix = prefix.strip().lower()
            rest = rest.strip()
            mapped = {
                "from": "from",
                "sender": "from",
                "domain": "domain",
                "subject": "subject",
                "title": "subject",
            }.get(prefix)
            if mapped:
                if not rest:
                    continue
                key = mapped
                value = rest

        value = value.strip().strip('"').strip("'")
        if not value:
            continue

        bucket = groups[key]
        lowered = value.lower()
        if lowered not in {x.lower() for x in bucket}:
            bucket.append(value)

    return MailSearchFilter(
        from_terms=tuple(groups["from"]),
        domain_terms=tuple(groups["domain"]),
        subject_terms=tuple(groups["subject"]),
    )


class ImapSession:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._client: IMAPClient | None = None

    def __enter__(self) -> "ImapSession":
        client = IMAPClient(self._host, port=self._port, ssl=True)
        client.login(self._user, self._password)
        self._client = client
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            try:
                # Some servers can emit extra untagged responses that confuse
                # IMAPClient during LOGOUT. LOGOUT errors are not actionable
                # for our workflow, so treat them as best-effort.
                try:
                    self._client.logout()
                except Exception:
                    pass
            finally:
                self._client = None

    @property
    def client(self) -> IMAPClient:
        if self._client is None:
            raise RuntimeError("IMAP client not connected")
        return self._client

    def list_folders(self) -> list[str]:
        folders = []
        for _flags, _delim, name in self.client.list_folders():
            folders.append(name)
        return folders

    def select_folder(self, folder: str, *, readonly: bool = False) -> None:
        self.client.select_folder(folder, readonly=bool(readonly))

    def get_uidvalidity(self) -> int:
        info = self.client.folder_status("INBOX", ["UIDVALIDITY"])
        uv = info.get(b"UIDVALIDITY") or info.get("UIDVALIDITY")
        return int(uv) if uv is not None else 0

    def get_uidvalidity_for(self, folder: str) -> int:
        info = self.client.folder_status(folder, ["UIDVALIDITY"])
        uv = info.get(b"UIDVALIDITY") or info.get("UIDVALIDITY")
        return int(uv) if uv is not None else 0

    def search_uids(
        self,
        sender_filter: str,
        since: dt.date | None,
        unseen_only: bool,
        min_uid_exclusive: int | None,
    ) -> list[int]:
        base: list[str] = []
        if unseen_only:
            base.append("UNSEEN")
        if since is not None:
            # Use RFC3501 date string to keep typing and server behavior stable.
            base.extend(["SINCE", since.strftime("%d-%b-%Y")])

        mail_filter = parse_mail_search_filter(sender_filter)

        def _run(criteria: list[str]) -> list[int]:
            if not criteria:
                criteria = ["ALL"]
            u = [int(x) for x in self.client.search(cast(Any, criteria))]
            u.sort()
            if min_uid_exclusive is not None:
                u = [x for x in u if x > min_uid_exclusive]
            return u

        groups: list[set[int]] = []

        def _run_many(field: str, terms: tuple[str, ...]) -> set[int]:
            found: set[int] = set()
            for term in terms:
                for uid in _run(list(base) + [field, term]):
                    found.add(int(uid))
            return found

        if mail_filter.from_terms:
            groups.append(_run_many("FROM", mail_filter.from_terms))
        if mail_filter.domain_terms:
            groups.append(
                _run_many(
                    "FROM", tuple(f"@{t.lstrip('@')}" for t in mail_filter.domain_terms)
                )
            )
        if mail_filter.subject_terms:
            groups.append(_run_many("SUBJECT", mail_filter.subject_terms))

        if not groups:
            return _run(list(base))

        matched = set(groups[0])
        for g in groups[1:]:
            matched &= g
        return sorted(matched)

    def iter_messages(
        self,
        uids: Iterable[int],
        *,
        chunk_size: int = 20,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Iterator[ImapMessage]:
        uid_list = [int(x) for x in uids]
        if not uid_list:
            return iter(())

        # Some servers are sensitive to large FETCH responses with literals.
        # Fetch metadata first (no literals), then raw message bodies with PEEK.
        def chunks(seq: list[int], n: int) -> list[list[int]]:
            return [seq[i : i + n] for i in range(0, len(seq), n)]

        fetched = 0
        total = len(uid_list)

        def gen() -> Iterator[ImapMessage]:
            nonlocal fetched
            for part in chunks(uid_list, max(1, int(chunk_size))):
                meta = cast(
                    Mapping[int, Mapping[bytes, Any]],
                    self.client.fetch(part, ["FLAGS", "INTERNALDATE"]),
                )

                try:
                    raw_map = cast(
                        Mapping[int, Mapping[bytes, Any]],
                        self.client.fetch(part, ["BODY.PEEK[]"]),
                    )
                except Exception:
                    # Fallback for servers that don't accept BODY.PEEK[].
                    raw_map = cast(
                        Mapping[int, Mapping[bytes, Any]],
                        self.client.fetch(part, ["RFC822"]),
                    )

                fetched += len(part)
                if on_progress is not None:
                    try:
                        on_progress(int(fetched), int(total))
                    except Exception:
                        pass

                for uid in part:
                    item: dict[bytes, Any] = {}
                    item.update(dict(meta.get(int(uid)) or {}))
                    item.update(dict(raw_map.get(int(uid)) or {}))

                    raw_any = (
                        item.get(b"RFC822")
                        or item.get(b"BODY[]")
                        or item.get(b"BODY.PEEK[]")
                    )
                    if isinstance(raw_any, (bytes, bytearray)):
                        raw = bytes(raw_any)
                    else:
                        raw = b""

                    internal_any = item.get(b"INTERNALDATE")
                    internal = (
                        internal_any if isinstance(internal_any, dt.datetime) else None
                    )

                    flags_any = item.get(b"FLAGS")
                    flags_list: list[bytes] = []
                    if isinstance(flags_any, tuple):
                        for f in flags_any:
                            if isinstance(f, bytes):
                                flags_list.append(f)

                    yield ImapMessage(
                        uid=int(uid),
                        rfc822=raw,
                        internaldate=internal,
                        flags=tuple(flags_list),
                    )

        return gen()

    def fetch_messages(self, uids: Iterable[int]) -> list[ImapMessage]:
        return list(self.iter_messages(uids, chunk_size=20, on_progress=None))

    def mark_seen(self, uid: int) -> None:
        # \Seen is the IMAP-standard read flag.
        self.client.add_flags([uid], ["\\Seen"], silent=True)

    def clear_seen(self, uid: int) -> None:
        # Best-effort: remove the read flag (useful for smoke tests).
        self.client.remove_flags([uid], ["\\Seen"], silent=True)
