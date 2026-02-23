from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobRow:
    id: str
    kind: str
    status: str
    progress_current: float
    progress_total: float
    message: str
    created_at: str
    updated_at: str


def find_active_job(conn: sqlite3.Connection, *, kind: str) -> JobRow | None:
    row = conn.execute(
        "SELECT id, kind, status, progress_current, progress_total, message, created_at, updated_at "
        "FROM jobs WHERE kind = ? AND status IN ('queued','running','cancel_requested') ORDER BY updated_at DESC LIMIT 1",
        (str(kind),),
    ).fetchone()
    if not row:
        return None
    return JobRow(
        id=str(row[0]),
        kind=str(row[1]),
        status=str(row[2]),
        progress_current=float(row[3]),
        progress_total=float(row[4]),
        message=str(row[5]),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def create_job(conn: sqlite3.Connection, *, job_id: str, kind: str) -> None:
    ts = _now()
    conn.execute(
        "INSERT INTO jobs(id, kind, status, progress_current, progress_total, message, created_at, updated_at) VALUES (?, ?, ?, 0, 0, '', ?, ?)",
        (job_id, kind, "queued", ts, ts),
    )
    conn.commit()


def set_job_status(
    conn: sqlite3.Connection, *, job_id: str, status: str, message: str = ""
) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
        (status, message, _now(), job_id),
    )
    conn.commit()


def update_progress(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    current: float,
    total: float,
    message: str,
) -> None:
    conn.execute(
        "UPDATE jobs SET progress_current = ?, progress_total = ?, message = ?, updated_at = ? WHERE id = ?",
        (float(current), float(total), message, _now(), job_id),
    )
    conn.commit()


def add_event(conn: sqlite3.Connection, *, job_id: str, level: str, text: str) -> None:
    conn.execute(
        "INSERT INTO job_events(job_id, ts, level, text) VALUES (?, ?, ?, ?)",
        (job_id, _now(), level, text),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> JobRow | None:
    row = conn.execute(
        "SELECT id, kind, status, progress_current, progress_total, message, created_at, updated_at FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    return JobRow(
        id=str(row[0]),
        kind=str(row[1]),
        status=str(row[2]),
        progress_current=float(row[3]),
        progress_total=float(row[4]),
        message=str(row[5]),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def get_events_since(
    conn: sqlite3.Connection, *, job_id: str, last_id: int
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, ts, level, text FROM job_events WHERE job_id = ? AND id > ? ORDER BY id ASC",
            (job_id, int(last_id)),
        ).fetchall()
    )
