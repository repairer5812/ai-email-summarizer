# AGENTS.md | webmail_summary/jobs

## Role: Background Process Orchestration
This directory handles long-running tasks: mail synchronization, LLM summarization, and Obsidian export. These jobs run asynchronously from the FastAPI request-response cycle to ensure UI responsiveness.

## Core Logic & Resilience
- **Sync Pipeline**: Archive -> Index -> Summarize -> Export -> Mark as Read.
- **IMAP Safety**: Uses `BODY.PEEK[]` during fetch to prevent implicit `\Seen` marking. Servers are only notified of `\Seen` after local archival and DB indexing are confirmed.
- **Process Isolation**: Sync jobs run in separate processes (`worker_sync.py`) via `subprocess.Popen`. This allows for reliable termination/cancellation without leaving the main app in an inconsistent state.
- **Resilient Export**: Obsidian export failures must not block the core summarization or the processing of subsequent emails.
    - Summarization happens *before* export to ensure metadata is captured even if the Markdown write fails.
    - Wrap export calls in try-except blocks to prevent a single IO error from crashing the entire sync job.
- **Error Handling**: Use the `repo.add_event` method to log specific failure details without halting the worker process when possible.
- **Cancellation**: Jobs should periodically check `cancel.is_set()` or respond to `SIGTERM` (on Windows via `taskkill`) to exit gracefully.

## Task Definitions
- `tasks_sync.py`: Main entry for periodic and manual IMAP syncing.
- `tasks_resummarize.py`: Utility for re-running LLM logic on existing archived mail.
- `tasks_refresh_overviews.py`: Synthesizes daily overviews from individual email summaries.
- `runner.py`: The central job runner that manages the queue and subprocess lifecycle.
- `repo.py`: Database access layer for job status, progress, and event logging.
- `worker_sync.py`: The standalone script used as the entry point for subprocess-based sync workers.
- `worker_probe.py`: Checks for running worker processes to avoid duplication or detect zombies.

## Progress & Monitoring
- **Repo Events**: Jobs must log significant events (errors, slow LLM responses) to the `job_events` table via `repo.py`.
- **Granular Progress**: Update progress percentages frequently (e.g., after each email or stage) to provide feedback to the UI.
- **Slow Job Detection**: Log warnings if archive or summarization stages take longer than expected (e.g., >15s for archive, >60s for LLM).
- **Obsidian Integration**: Always generate Daily and Topic-based index files. Backlinks and tags should be formatted for native Obsidian compatibility.

## Implementation Guidelines
- **No Global State**: Workers should reload settings from the DB at the start of each run.
- **Database Hygiene**: Use short-lived connections (`get_conn`) within job loops to avoid locking issues with the web server.
- **Zombie Prevention**: Use `worker_probe.py` to identify and cleanup orphaned sync processes on startup.
- **Post-processing Resilience**: Failure in daily digest generation should not invalidate successful archival.
