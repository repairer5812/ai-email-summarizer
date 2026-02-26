from __future__ import annotations

import sqlite3
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Increase timeout to reduce "database is locked" errors
    # when background jobs and UI requests overlap.
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Reasonable defaults for local app
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_db(db_path: Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        cur = conn.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (0)")
            conn.commit()

        version = int(conn.execute("SELECT version FROM schema_version").fetchone()[0])
        target = 4
        if version < 1:
            _migrate_0_to_1(conn)
            conn.execute("UPDATE schema_version SET version = 1")
            conn.commit()
            version = 1
        if version < 2:
            _migrate_1_to_2(conn)
            conn.execute("UPDATE schema_version SET version = 2")
            conn.commit()
            version = 2
        if version < 3:
            _migrate_2_to_3(conn)
            conn.execute("UPDATE schema_version SET version = 3")
            conn.commit()
            version = 3
        if version < 4:
            _migrate_3_to_4(conn)
            conn.execute("UPDATE schema_version SET version = 4")
            conn.commit()
            version = 4

        if version > target:
            raise RuntimeError(f"DB schema too new: {version} > {target}")
    finally:
        conn.close()


def get_conn(db_path: Path) -> sqlite3.Connection:
    return _connect(db_path)


def _migrate_0_to_1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          progress_current INTEGER NOT NULL DEFAULT 0,
          progress_total INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          ts TEXT NOT NULL,
          level TEXT NOT NULL,
          text TEXT NOT NULL,
          FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id TEXT NOT NULL,
          mailbox TEXT NOT NULL,
          uidvalidity INTEGER NOT NULL,
          uid INTEGER NOT NULL,
          message_id TEXT,
          internal_date TEXT,
          from_addr TEXT,
          to_addr TEXT,
          subject TEXT,
          raw_eml_path TEXT NOT NULL,
          body_html_path TEXT,
          body_text_path TEXT,
          rendered_html_path TEXT,
          summary TEXT,
          tags_json TEXT,
          backlinks_json TEXT,
          topics_json TEXT,
          personal INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT,
          indexed_at TEXT,
          exported_at TEXT,
          seen_marked_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(account_id, mailbox, uidvalidity, uid)
        );

        CREATE TABLE IF NOT EXISTS attachments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_fk INTEGER NOT NULL,
          filename TEXT NOT NULL,
          mime_type TEXT,
          size_bytes INTEGER NOT NULL,
          rel_path TEXT NOT NULL,
          content_id TEXT,
          is_inline INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          FOREIGN KEY(message_fk) REFERENCES messages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS external_assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_fk INTEGER NOT NULL,
          original_url TEXT NOT NULL,
          rel_path TEXT,
          mime_type TEXT,
          size_bytes INTEGER,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(message_fk) REFERENCES messages(id) ON DELETE CASCADE
        );
        """
    )


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    # Add summarization timing metrics.
    cols = {
        str(r[1])
        for r in conn.execute("PRAGMA table_info(messages)").fetchall()
        if r and r[1]
    }
    if "summarized_at" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN summarized_at TEXT")
    if "summarize_ms" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN summarize_ms INTEGER")


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_overviews (
          day TEXT PRIMARY KEY,
          overview TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )


def _migrate_3_to_4(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_internal_date ON messages(internal_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_day_prefix ON messages(substr(internal_date, 1, 10))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pending_summary ON messages(id) WHERE summarized_at IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sync_resume ON messages(account_id, mailbox, uidvalidity, uid) WHERE seen_marked_at IS NOT NULL")

