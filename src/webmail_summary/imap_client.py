from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, cast

from imapclient import IMAPClient


@dataclass(frozen=True)
class ImapMessage:
    uid: int
    rfc822: bytes
    internaldate: dt.datetime | None
    flags: tuple[bytes, ...]


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
        sender: str,
        since: dt.date | None,
        unseen_only: bool,
        min_uid_exclusive: int | None,
    ) -> list[int]:
        criteria: list[str] = []
        if unseen_only:
            criteria.append("UNSEEN")
        criteria.extend(["FROM", sender])
        if since is not None:
            # Use RFC3501 date string to keep typing and server behavior stable.
            criteria.extend(["SINCE", since.strftime("%d-%b-%Y")])

        # IMAPClient.search supports list criteria, but type stubs can be strict.
        uids = [int(x) for x in self.client.search(cast(Any, criteria))]
        uids.sort()
        if min_uid_exclusive is not None:
            uids = [u for u in uids if u > min_uid_exclusive]
        return uids

    def fetch_messages(self, uids: Iterable[int]) -> list[ImapMessage]:
        uid_list = [int(x) for x in uids]
        if not uid_list:
            return []

        # Some servers are sensitive to large FETCH responses with literals.
        # Fetch metadata first (no literals), then raw message bodies with PEEK.
        def chunks(seq: list[int], n: int) -> list[list[int]]:
            return [seq[i : i + n] for i in range(0, len(seq), n)]

        out: list[ImapMessage] = []
        for part in chunks(uid_list, 20):
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

                out.append(
                    ImapMessage(
                        uid=int(uid),
                        rfc822=raw,
                        internaldate=internal,
                        flags=tuple(flags_list),
                    )
                )

        return out

    def mark_seen(self, uid: int) -> None:
        # \Seen is the IMAP-standard read flag.
        self.client.add_flags([uid], ["\\Seen"], silent=True)

    def clear_seen(self, uid: int) -> None:
        # Best-effort: remove the read flag (useful for smoke tests).
        self.client.remove_flags([uid], ["\\Seen"], silent=True)
