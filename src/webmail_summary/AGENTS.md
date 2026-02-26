# AGENTS.md | webmail_summary Core

## Meta Context
- **Role**: Sisyphus-Junior (Task Executor)
- **Tech Stack**: Python 3.10+, FastAPI, SQLite, IMAPClient, llama.cpp, OpenRouter.
- **Goal**: Core logic for IMAP archiving, LLM processing, and local web serving.

## Package Structure (src/webmail_summary)
- `cli.py`: Entry point for command line (`webmail-summary serve`, `sync`).
- `__main__.py`: Allows execution via `python -m webmail_summary`.
- `app/`: FastAPI application. `main.py` handles lifecycle and port discovery.
- `api/`: REST endpoints for background jobs and UI communication.
- `ui/`: Jinja2 templates, static assets, and web routes.
- `index/`: SQLite (`db.py`) and mailbox repository management.
- `jobs/`: Background task runner and specific workers (sync, resummarize).
- `llm/`: LLM provider abstraction (Local llama.cpp, OpenRouter, Ollama).
- `archive/`: EML parsing, attachment handling, and HTML rewriting/sanitization.
- `util/`: Low-level helpers (net, atomic_io, app_data, text_sanitize).

## Architecture & Entry Points
- **CLI Entry**: `cli.main()` handles command routing. 
- **Server Entry**: `app/main.py:serve` initializes DB, clears stale jobs, and starts Uvicorn.
- **Database**: SQLite with WAL mode. Stored in `%LOCALAPPDATA%\webmail-summary`.
- **Background Jobs**: custom runner in `jobs/runner.py`. Jobs are persisted in DB.

## Development Guidelines
- **Modifying UI**: Routes are in `ui/routes.py`, templates in `ui/templates`.
- **Modifying AI**: All providers inherit from `llm/base.py`. Local engine uses `llm/local_engine.py`.
- **Mail Processing**: `archive/pipeline.py` defines the flow from EML to local archive.
- **Path Handling**: Use `util/app_data.py` to resolve local storage paths.

## Key Files
- `src/webmail_summary/cli.py`: Argparse configuration.
- `src/webmail_summary/app/main.py`: FastAPI app factory and `serve` logic.
- `src/webmail_summary/index/db.py`: Schema migrations and connection management.
- `src/webmail_summary/jobs/tasks_sync.py`: Main IMAP synchronization loop.
- `src/webmail_summary/archive/html_rewrite.py`: External asset download and `cid:` replacement.
