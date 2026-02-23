from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MessageRow:
    id: int
    account_id: str
    mailbox: str
    uidvalidity: int
    uid: int
    subject: str
    archived_at: str | None
    exported_at: str | None
    seen_marked_at: str | None


def get_existing_message(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    mailbox: str,
    uidvalidity: int,
    uid: int,
) -> MessageRow | None:
    row = conn.execute(
        "SELECT id, account_id, mailbox, uidvalidity, uid, subject, archived_at, exported_at, seen_marked_at FROM messages WHERE account_id=? AND mailbox=? AND uidvalidity=? AND uid=?",
        (account_id, mailbox, int(uidvalidity), int(uid)),
    ).fetchone()
    if not row:
        return None
    return MessageRow(
        id=int(row[0]),
        account_id=str(row[1]),
        mailbox=str(row[2]),
        uidvalidity=int(row[3]),
        uid=int(row[4]),
        subject=str(row[5] or ""),
        archived_at=str(row[6]) if row[6] else None,
        exported_at=str(row[7]) if row[7] else None,
        seen_marked_at=str(row[8]) if row[8] else None,
    )


def upsert_message(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    mailbox: str,
    uidvalidity: int,
    uid: int,
    message_id: str | None,
    internal_date: str | None,
    from_addr: str | None,
    to_addr: str | None,
    subject: str | None,
    raw_eml_path: str,
    body_html_path: str | None,
    body_text_path: str | None,
    rendered_html_path: str | None,
) -> int:
    ts = _now()
    conn.execute(
        """
        INSERT INTO messages(
          account_id, mailbox, uidvalidity, uid, message_id, internal_date, from_addr, to_addr, subject,
          raw_eml_path, body_html_path, body_text_path, rendered_html_path,
          created_at, updated_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, mailbox, uidvalidity, uid)
        DO UPDATE SET
          message_id=excluded.message_id,
          internal_date=excluded.internal_date,
          from_addr=excluded.from_addr,
          to_addr=excluded.to_addr,
          subject=excluded.subject,
          raw_eml_path=excluded.raw_eml_path,
          body_html_path=excluded.body_html_path,
          body_text_path=excluded.body_text_path,
          rendered_html_path=excluded.rendered_html_path,
          updated_at=excluded.updated_at,
          archived_at=COALESCE(messages.archived_at, excluded.archived_at)
        """,
        (
            account_id,
            mailbox,
            int(uidvalidity),
            int(uid),
            message_id,
            internal_date,
            from_addr,
            to_addr,
            subject,
            raw_eml_path,
            body_html_path,
            body_text_path,
            rendered_html_path,
            ts,
            ts,
            ts,
        ),
    )
    row = conn.execute(
        "SELECT id FROM messages WHERE account_id=? AND mailbox=? AND uidvalidity=? AND uid=?",
        (account_id, mailbox, int(uidvalidity), int(uid)),
    ).fetchone()
    return int(row[0])


def replace_attachments(
    conn: sqlite3.Connection, *, message_fk: int, items: list[dict]
) -> None:
    ts = _now()
    conn.execute("DELETE FROM attachments WHERE message_fk = ?", (int(message_fk),))
    for it in items:
        conn.execute(
            "INSERT INTO attachments(message_fk, filename, mime_type, size_bytes, rel_path, content_id, is_inline, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(message_fk),
                str(it["filename"]),
                it.get("mime_type"),
                int(it["size_bytes"]),
                str(it["rel_path"]),
                it.get("content_id"),
                1 if it.get("is_inline") else 0,
                ts,
            ),
        )


def replace_external_assets(
    conn: sqlite3.Connection, *, message_fk: int, items: list[dict]
) -> None:
    ts = _now()
    conn.execute("DELETE FROM external_assets WHERE message_fk = ?", (int(message_fk),))
    for it in items:
        conn.execute(
            "INSERT INTO external_assets(message_fk, original_url, rel_path, mime_type, size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(message_fk),
                str(it["original_url"]),
                it.get("rel_path"),
                it.get("mime_type"),
                it.get("size_bytes"),
                str(it.get("status") or ""),
                ts,
            ),
        )


def set_analysis(
    conn: sqlite3.Connection,
    *,
    message_fk: int,
    summary: str,
    tags: list[str],
    topics: list[str],
    personal: bool,
    summarized_at: str | None = None,
    summarize_ms: int | None = None,
) -> None:
    ts = _now()
    sat = summarized_at or ts
    conn.execute(
        "UPDATE messages SET summary=?, tags_json=?, topics_json=?, personal=?, indexed_at=?, summarized_at=?, summarize_ms=?, updated_at=? WHERE id=?",
        (
            summary,
            json.dumps(tags, ensure_ascii=True),
            json.dumps(topics, ensure_ascii=True),
            1 if personal else 0,
            ts,
            sat,
            int(summarize_ms) if summarize_ms is not None else None,
            ts,
            int(message_fk),
        ),
    )


def set_exported(
    conn: sqlite3.Connection, *, message_fk: int, exported_at: str | None = None
) -> None:
    ts = exported_at or _now()
    conn.execute(
        "UPDATE messages SET exported_at=?, updated_at=? WHERE id=?",
        (ts, ts, int(message_fk)),
    )


def set_seen_marked(conn: sqlite3.Connection, *, message_fk: int) -> None:
    ts = _now()
    conn.execute(
        "UPDATE messages SET seen_marked_at=?, updated_at=? WHERE id=?",
        (ts, ts, int(message_fk)),
    )


def get_max_uid(
    conn: sqlite3.Connection, *, account_id: str, mailbox: str, uidvalidity: int
) -> int | None:
    row = conn.execute(
        "SELECT MAX(uid) FROM messages WHERE account_id=? AND mailbox=? AND uidvalidity=? AND seen_marked_at IS NOT NULL",
        (account_id, mailbox, int(uidvalidity)),
    ).fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def list_messages_by_date(
    conn: sqlite3.Connection, *, date_prefix: str
) -> list[sqlite3.Row]:
    # date_prefix: 'YYYY-MM-DD'
    return list(
        conn.execute(
            "SELECT id, subject, from_addr, internal_date, summary, tags_json, topics_json, raw_eml_path, rendered_html_path, summarized_at, summarize_ms FROM messages WHERE internal_date LIKE ? ORDER BY internal_date ASC",
            (f"{date_prefix}%",),
        ).fetchall()
    )


def list_recent_messages(
    conn: sqlite3.Connection, *, limit: int = 50
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, subject, from_addr, internal_date, summary, tags_json, topics_json, rendered_html_path, summarized_at, summarize_ms FROM messages ORDER BY internal_date DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    )


def get_message_detail(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, subject, from_addr, to_addr, internal_date, summary, tags_json, topics_json, raw_eml_path, rendered_html_path, summarized_at, summarize_ms FROM messages WHERE id = ?",
        (int(message_id),),
    ).fetchone()


def list_messages_for_resummarize_by_date(
    conn: sqlite3.Connection, *, date_prefix: str
) -> list[sqlite3.Row]:
    # Includes fields required for recomputing message_key and reading archived bodies.
    return list(
        conn.execute(
            "SELECT id, account_id, mailbox, uidvalidity, uid, subject, from_addr, internal_date, summary, raw_eml_path, body_text_path, body_html_path "
            "FROM messages WHERE internal_date LIKE ? ORDER BY internal_date ASC",
            (f"{date_prefix}%",),
        ).fetchall()
    )


def list_messages_for_resummarize_by_ids(
    conn: sqlite3.Connection, *, message_ids: list[int]
) -> list[sqlite3.Row]:
    mids = [int(x) for x in (message_ids or []) if str(x).strip()]
    if not mids:
        return []
    qmarks = ",".join(["?"] * len(mids))
    sql = (
        "SELECT id, account_id, mailbox, uidvalidity, uid, subject, from_addr, internal_date, summary, raw_eml_path, body_text_path, body_html_path "
        f"FROM messages WHERE id IN ({qmarks}) ORDER BY internal_date ASC"
    )
    return list(conn.execute(sql, tuple(mids)).fetchall())


def get_daily_overview(conn: sqlite3.Connection, day: str) -> str | None:
    row = conn.execute(
        "SELECT overview FROM daily_overviews WHERE day = ?", (day,)
    ).fetchone()
    return str(row[0]) if row else None


def set_daily_overview(conn: sqlite3.Connection, day: str, overview: str) -> None:
    conn.execute(
        "INSERT INTO daily_overviews(day, overview, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET overview=excluded.overview, updated_at=excluded.updated_at",
        (day, overview, _now()),
    )
