# AGENTS.md | webmail_summary Core

## Meta Context
- **Role**: Sisyphus-Junior (Task Executor)
- **Tech Stack**: Python 3.10+, FastAPI, SQLite, IMAPClient; LLMs via llama.cpp, MLX (Apple Silicon) or cloud APIs; pywebview + pystray for the Windows window and tray.
- **Goal**: Core logic for IMAP archiving, LLM processing, and local web serving.

## Package Structure (src/webmail_summary)
- `cli.py`: Entry point for command line (`webmail-summary ui`, `serve`, `sync`, `sync-worker`).
- `__main__.py`: Allows execution via `python -m webmail_summary`.
- `app/`: FastAPI application. `main.py` builds the app, `serve.py` runs uvicorn, port discovery and the close watchdog.
- `api/`: REST endpoints for background jobs and UI communication.
- `ui/`: Jinja2 templates, static assets, web routes, the Windows launcher (`native_window.py`) and the updater (`updates.py`, `resources/apply_update.ps1`).
- `index/`: SQLite (`db.py`) and mailbox repository management.
- `jobs/`: Background task runner and specific workers (sync, resummarize); shared LLM call helpers in `llm_call.py`.
- `llm/`: LLM provider abstraction (local llama.cpp, MLX, cloud providers listed in `cloud_registry.py`).
- `archive/`: EML parsing, attachment handling, and HTML rewriting/sanitization.
- `util/`: Low-level helpers (net, atomic_io, app_data, text_sanitize).

## Architecture & Entry Points
- **CLI Entry**: `cli.main()` handles command routing. 
- **Server Entry**: `app/serve.py:serve` starts Uvicorn; `app/main.py:create_app` initializes the DB and clears stale jobs.
- **Database**: SQLite with WAL mode at `index.db.app_db_path()` (`%LOCALAPPDATA%\WebmailSummary\db.sqlite3` on Windows). Open it with `with open_db(path) as conn:`.
- **Background Jobs**: custom runner in `jobs/runner.py`. Jobs are persisted in DB.

## Development Guidelines
- **Modifying UI**: Routes are in `ui/routes.py`, templates in `ui/templates`.
- **Modifying AI**: All providers inherit from `llm/base.py`. Local engine uses `llm/local_engine.py`.
- **Mail Processing**: `archive/pipeline.py` defines the flow from EML to local archive.
- **Path Handling**: Use `util/app_data.py` to resolve local storage paths.

## Key Files
- `src/webmail_summary/cli.py`: Argparse configuration.
- `src/webmail_summary/app/main.py`: FastAPI app factory; `app/serve.py`: `serve` logic.
- `src/webmail_summary/index/db.py`: Schema migrations and connection management.
- `src/webmail_summary/jobs/tasks_sync.py`: Main IMAP synchronization loop (`_SyncRun` + step functions).
- `src/webmail_summary/jobs/llm_call.py`: LLM pacing, deadline, heartbeat and image inputs shared by sync and resummarize.
- `src/webmail_summary/llm/cloud_registry.py`: Cloud provider table, endpoints and auth headers.
- `src/webmail_summary/archive/html_rewrite.py`: External asset download and `cid:` replacement.
