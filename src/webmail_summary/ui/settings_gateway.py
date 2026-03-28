from __future__ import annotations

from pathlib import Path

from webmail_summary.util.app_data import get_app_data_dir


def db_path() -> Path:
    return get_app_data_dir() / "db.sqlite3"


def get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
