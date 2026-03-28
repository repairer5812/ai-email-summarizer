# Architecture Overview

This project is a local-first desktop mail workflow app.

Its main job is:

1. fetch mail from IMAP,
2. archive raw and rendered artifacts locally,
3. index metadata in SQLite,
4. summarize content with an LLM,
5. export notes into Obsidian,
6. expose everything through a local FastAPI + Jinja UI.

## Top-Level Runtime Model

- Entry command: `webmail-summary`
- Primary CLI: `src/webmail_summary/cli.py`
- App factory: `src/webmail_summary/app/main.py`
- UI route entry: `src/webmail_summary/ui/routes.py`
- UI route domains: `src/webmail_summary/ui/routes_home.py`, `src/webmail_summary/ui/routes_messages.py`, `src/webmail_summary/ui/routes_setup.py`, `src/webmail_summary/ui/routes_lifecycle.py`
- Job API: `src/webmail_summary/api/routes_jobs.py`
- OpenRouter/model API: `src/webmail_summary/api/routes_openrouter.py`

On Windows, launching without a subcommand opens the native desktop wrapper.
On non-Windows, it starts the local FastAPI server in browser mode.

## Main Data Flow

### 1. App startup

- `src/webmail_summary/cli.py` decides whether to run UI, server, or worker commands.
- `src/webmail_summary/app/main.py:create_app()` initializes the DB, mounts static files, and wires routers.
- Startup also marks stale in-progress jobs as recovered terminal states so the UI does not keep watching dead job IDs.

### 2. Settings and secrets

- Persistent app settings live in SQLite table `settings`.
- Settings contract and normalization live in `src/webmail_summary/index/settings.py`.
- Passwords and cloud API keys are stored in OS keyring, not in SQLite.

### 3. Background jobs

- Job orchestration lives in `src/webmail_summary/jobs/runner.py`.
- Job state is persisted in SQLite tables `jobs` and `job_events`.
- Sync jobs run as a subprocess worker so cancellation is immediate and isolated.

### 4. Mail sync pipeline

The main pipeline lives in `src/webmail_summary/jobs/tasks_sync.py`.

For each message, it does roughly this:

1. fetch raw RFC822 bytes from IMAP,
2. archive files locally,
3. write or update DB records,
4. prepare body text for summarization,
5. run LLM summarization,
6. save summary/tags/topics,
7. export the result into Obsidian,
8. mark IMAP message as seen after successful local processing.

### 5. Archive layer

- `src/webmail_summary/archive/pipeline.py` writes `raw.eml`, `body.txt`, `body.html`, `rendered.html`.
- `src/webmail_summary/archive/mime_parts.py` extracts attachments.
- `src/webmail_summary/archive/html_rewrite.py` rewrites `cid:` and downloads external assets.
- `src/webmail_summary/archive/html_sanitize.py` sanitizes rewritten HTML before rendering.

### 6. LLM layer

- `src/webmail_summary/llm/provider.py` chooses the backend.
- Local mode uses llama.cpp binaries/server if installed.
- Cloud mode uses provider-specific API keys from keyring.
- `src/webmail_summary/llm/long_summarize.py` is the long-email strategy layer with chunking, synthesis, cleanup, and fallback heuristics.

### 7. UI layer

- `src/webmail_summary/ui/routes.py` is now a thin aggregator that includes domain routers.
- `src/webmail_summary/ui/routes_home.py` serves dashboard and day-card API endpoints.
- `src/webmail_summary/ui/routes_messages.py` serves day view, message detail, original view, and archived file responses.
- `src/webmail_summary/ui/routes_setup.py` serves setup GET/POST flows.
- `src/webmail_summary/ui/routes_lifecycle.py` serves lifecycle/shutdown endpoints.
- `src/webmail_summary/ui/updates.py` owns update checking and installer/apply endpoints.
- Templates live in `src/webmail_summary/ui/templates/`.
- CSS and static assets live in `src/webmail_summary/ui/static/`.

### 8. Export layer

- `src/webmail_summary/export/obsidian/exporter.py` writes message notes, daily notes, and topic notes into the configured vault.

## Storage Model

### SQLite tables

Defined in `src/webmail_summary/index/db.py`.

Main tables:

- `settings`: key-value configuration
- `jobs`: background job state
- `job_events`: job timeline/event log
- `messages`: archived message metadata and summary state
- `attachments`: extracted attachment metadata
- `external_assets`: downloaded remote asset metadata
- `daily_overviews`: per-day overview text

### Local file artifacts

Archived message directories store:

- `raw.eml`
- `body.txt`
- `body.html`
- `rendered.html`
- `attachments/`
- `external/`

## Reading Order For New Maintainers

Read these files in this order:

1. `src/webmail_summary/cli.py`
2. `src/webmail_summary/app/main.py`
3. `src/webmail_summary/index/db.py`
4. `src/webmail_summary/index/settings.py`
5. `src/webmail_summary/jobs/runner.py`
6. `src/webmail_summary/jobs/tasks_sync.py`
7. `src/webmail_summary/archive/pipeline.py`
8. `src/webmail_summary/llm/provider.py`
9. `src/webmail_summary/llm/long_summarize.py`
10. `src/webmail_summary/ui/routes.py`
11. `src/webmail_summary/ui/routes_setup.py`
12. `src/webmail_summary/ui/routes_home.py`
13. `src/webmail_summary/ui/routes_messages.py`
14. `src/webmail_summary/ui/updates.py`
15. `src/webmail_summary/export/obsidian/exporter.py`

## Current Architectural Strengths

- Local-first design is consistent.
- Secrets stay out of SQLite.
- SQLite is configured for local concurrency with WAL and busy timeout.
- Sync runs in a subprocess, which improves cancellation behavior.
- The archive layer keeps raw and rendered data, which is good for debugging and reprocessing.

## Main Maintainability Risks

### 1. `ui/updates.py` is still a high-impact hotspot

The old `ui/routes.py` god-module pressure has been reduced, but update/apply logic still owns Windows installer handoff, shutdown, verification, and process control in one place.

### 2. `tasks_sync.py` is too monolithic

It mixes IMAP, archival, DB persistence, LLM work, export, progress reporting, and retry logic in one pipeline function.

### 3. `long_summarize.py` is a heuristic hotspot

Many behaviors depend on interlocked rules. Small changes can cause broad regressions.

### 4. Settings and provider logic have duplication

Some setting helpers and cloud-provider defaults exist in more than one place.

## Refactor Priorities

### Priority 1

Continue reducing domain coupling after the route split by consolidating settings access and further shrinking update/setup internals.

### Priority 2

Unify settings access through `src/webmail_summary/index/settings.py`.

### Priority 3

Break `src/webmail_summary/jobs/tasks_sync.py` into explicit pipeline steps.

### Priority 4

Extract and test `long_summarize.py` heuristics in smaller units.

## Safe Mental Model

Think of the app as four connected subsystems:

- ingestion: IMAP -> archive -> DB
- intelligence: body prep -> summarize -> tag/topic extraction
- presentation: dashboard/setup/message views
- export: Obsidian notes and linked assets

When changing code, first decide which subsystem owns the behavior.
That reduces the chance of fixing a symptom in the wrong layer.
