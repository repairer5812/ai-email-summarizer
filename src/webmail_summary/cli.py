from __future__ import annotations

import argparse
import platform

from webmail_summary.util.ssl_certs import configure_requests_ca_bundle

from webmail_summary.app.main import ServeOptions, serve
from webmail_summary.jobs.runner import get_runner
from webmail_summary.jobs.tasks_sync import sync_mailbox_task
from webmail_summary.jobs.worker_sync import run_worker
from webmail_summary.ui.native_window import run_ui


def main(argv: list[str] | None = None) -> None:
    configure_requests_ca_bundle()
    parser = argparse.ArgumentParser(prog="webmail-summary")
    # Treat missing subcommand as launching the app UI.
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")

    p_ui = sub.add_parser("ui")
    p_ui.add_argument("--port", type=int, default=0)

    sub.add_parser("sync")
    p_sync_worker = sub.add_parser("sync-worker")
    p_sync_worker.add_argument("--job-id", required=True)

    args = parser.parse_args(argv)

    if args.cmd in {None, "ui"}:
        p = None
        if args.cmd == "ui":
            p = int(args.port) if int(args.port) > 0 else None
        if (platform.system() or "").strip().lower() == "windows":
            run_ui(port=p)
            return
        # Non-Windows environments keep the browser flow.
        serve(ServeOptions(port=p, open_browser=True))
        return

    if args.cmd == "serve":
        port = int(args.port) if int(args.port) > 0 else None
        open_browser = not args.no_browser
        serve(ServeOptions(port=port, open_browser=open_browser))
        return
    if args.cmd == "sync":
        job_id = get_runner().enqueue(kind="sync", fn=sync_mailbox_task())
        print(job_id)
        return
    if args.cmd == "sync-worker":
        run_worker(str(args.job_id))
        return


if __name__ == "__main__":
    main()
