from __future__ import annotations

import argparse
import threading

from webmail_summary.index.db import get_conn
from webmail_summary.jobs import repo
from webmail_summary.jobs.tasks_sync import sync_mailbox_task
from webmail_summary.util.app_data import get_app_data_dir


def main() -> None:
    p = argparse.ArgumentParser(prog="webmail-summary-sync-worker")
    p.add_argument("--job-id", required=True)
    args = p.parse_args()
    job_id = str(args.job_id)

    db_path = get_app_data_dir() / "db.sqlite3"

    conn = get_conn(db_path)
    try:
        repo.set_job_status(conn, job_id=job_id, status="running")
        repo.add_event(conn, job_id=job_id, level="info", text="sync worker started")
    finally:
        conn.close()

    cancel = threading.Event()
    try:
        sync_mailbox_task()(job_id, cancel)
    except Exception as e:
        conn2 = get_conn(db_path)
        try:
            repo.add_event(conn2, job_id=job_id, level="error", text=str(e))
            # Only mark failed if not already cancelled.
            job = repo.get_job(conn2, job_id)
            if job is not None and job.status not in {"cancelled"}:
                repo.set_job_status(
                    conn2, job_id=job_id, status="failed", message=str(e)
                )
        finally:
            conn2.close()
        raise
    else:
        conn3 = get_conn(db_path)
        try:
            job = repo.get_job(conn3, job_id)
            if job is not None and job.status not in {"cancelled"}:
                repo.set_job_status(conn3, job_id=job_id, status="succeeded")
        finally:
            conn3.close()


if __name__ == "__main__":
    main()
