from __future__ import annotations

import argparse

from webmail_summary.app.main import ServeOptions, serve
from webmail_summary.jobs.runner import get_runner
from webmail_summary.jobs.tasks_sync import sync_mailbox_task


def main() -> None:
    parser = argparse.ArgumentParser(prog="webmail-summary")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")

    sub.add_parser("sync")

    args = parser.parse_args()
    if args.cmd == "serve":
        port = int(args.port) if int(args.port) > 0 else None
        serve(ServeOptions(port=port, open_browser=not args.no_browser))
        return
    if args.cmd == "sync":
        job_id = get_runner().enqueue(kind="sync", fn=sync_mailbox_task())
        print(job_id)
        return


if __name__ == "__main__":
    main()
