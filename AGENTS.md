# PROJECT KNOWLEDGE BASE (webmail_summary)

**Updated:** 2026-10-24 (structure after the jobs/llm/index refactor)
**Branch:** main

## OVERVIEW
Local-first mail archiving, LLM summaries and Obsidian export. Python 3.10+
(CI and releases use 3.11), FastAPI + Uvicorn, IMAPClient, SQLite.

- **Windows (shipped app)**: PyInstaller onedir build plus Inno Setup
  installer. The UI is a pywebview native window (WebView2 through
  pythonnet) with a pystray tray icon. When the native window cannot start
  (no .NET runtime, WebView2 blocked), the app opens the browser (app mode
  when available) and keeps a fallback tray.
- **macOS / Linux**: source-based browser mode only (`webmail-summary serve`
  or `ui`); there is no native window or tray there.
- **LLM backends**: local llama.cpp (persistent `llama-server`, falling back
  to `llama-cli`), MLX (`mlx-lm`) on Apple Silicon, or a cloud provider
  (OpenAI, Anthropic, Google Gemini, Upstage, OpenRouter).

## STRUCTURE
```
src/webmail_summary/
├── cli.py            # serve | ui | sync | sync-worker
├── app/              # FastAPI app factory (main.py), uvicorn + lifecycle (serve.py)
├── api/              # job API + SSE (routes_jobs.py), OpenRouter model list
├── ui/               # page routes, templates/, static/, i18n
│   ├── native_window.py   # Windows launcher: pywebview window, fallback tray
│   ├── updates.py         # GitHub release check and in-app updater
│   └── resources/         # apply_update.ps1 (run by the updater)
├── jobs/             # runner, sync/resummarize/overview/local-install tasks
│   └── llm_call.py        # shared LLM pacing, deadline, heartbeat, image inputs
├── llm/              # providers: llama.cpp, MLX, cloud; long-mail pipeline
│   └── cloud_registry.py  # cloud provider table, endpoints, auth headers
├── archive/          # EML parsing, attachments, HTML rewrite/sanitize
├── export/obsidian/  # Mail / Daily / Topic notes
├── index/            # SQLite: db.py (paths, open_db, migrations), mail_repo, settings
└── util/             # app_data paths, platform caps, process control, text cleanup
installer/            # Inno Setup script, PyInstaller runtime hook
landing/              # Next.js landing page (GitHub Pages)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Startup | `cli.py` | `ui` uses the native window when `ui_platform_caps()` allows it |
| Windows launcher | `ui/native_window.py` | server child process, WebView2 retry, browser fallback, tray |
| Web server | `app/serve.py`, `app/main.py` | loopback Host/Origin guard, `active_url.txt` handshake |
| DB | `index/db.py` | `app_db_path()`, `open_db()` (closes, never commits), migrations |
| Settings | `index/settings.py` | `load_settings`, `get_setting`, `set_setting` |
| Sync job | `jobs/tasks_sync.py` | `_SyncRun` + steps: fetch, archive, summarize, save/export, mark |
| Resummarize job | `jobs/tasks_resummarize.py` | `_ResummarizeRun` + per-message steps |
| LLM call helpers | `jobs/llm_call.py` | used by both jobs; keep them in one place |
| Cloud providers | `llm/cloud_registry.py` | add a provider here, not in provider.py or setup_service.py |
| Local models | `llm/local_models.py`, `llm/local_engine.py`, `llm/mlx_*` | |
| Updater | `ui/updates.py`, `ui/resources/apply_update.ps1` | script is copied next to the installer and run with `powershell -File` |
| Release | `.github/workflows/release.yml` | runs only on `v*` tags |

## ARCHITECTURE GUIDELINES
- **Storage**: metadata in SQLite; raw .eml, bodies and attachments under the
  app data dir: `%LOCALAPPDATA%\WebmailSummary` (Windows),
  `~/Library/Application Support/WebmailSummary` (macOS),
  `$XDG_DATA_HOME/WebmailSummary` (Linux). Use `util/app_data.py` and
  `index.db.app_db_path()`; do not join `db.sqlite3` by hand.
- **Secrets**: IMAP passwords and API keys live in `keyring` only
  (`webmail-summary::<host or provider>`). Never in SQLite or plain files.
  Gemini keys go in the `x-goog-api-key` header, not the URL.
- **IMAP**: fetch with `BODY.PEEK[]`; set `\Seen` only after the mail is
  archived, indexed, summarized and exported. Failed mails keep
  `seen_marked_at = NULL` and are retried on the next sync.
- **HTML**: rewrite `cid:` and download external assets to local paths.
- **LLM cleanup**: strip footers and legal noise before summarizing.
- **DB connections**: short-lived, `with open_db(path) as conn:`; call
  `conn.commit()` explicitly.

## DEVELOPMENT COMMANDS
```powershell
# Windows: venv, editable install, start the server
.\run_dev.ps1
webmail-summary ui        # native window (Windows)
webmail-summary serve     # browser mode, any OS
```
```bash
# Tests (CI only runs compileall; run pytest locally)
python -m pytest -p no:cacheprovider
ruff check --no-cache src tests
```
Tests never touch real IMAP, SMTP, LLM APIs or GitHub: `tests/conftest.py`
points the app data dir at `tmp_path`, and network calls are faked.

## ANTI-PATTERNS
- **Secrets in DB or URLs**: always use keyring; no API keys in query strings.
- **Copy-pasted provider tables or LLM call loops**: extend
  `llm/cloud_registry.py` and `jobs/llm_call.py` instead.
- **Image proxy**: download assets locally; don't rely on server-side optimization.
- **Raw LLM noise**: summaries must be concise and free of legal/technical footers.

## DOCUMENTATION HIERARCHY
- **./AGENTS.md**: Root overview and project rules.
- **src/webmail_summary/AGENTS.md**: Core package structure and entry points.
- **src/webmail_summary/llm/AGENTS.md**: LLM provider logic and noise removal.
- **src/webmail_summary/ui/AGENTS.md**: Templates, static assets, and i18n.
- **src/webmail_summary/jobs/AGENTS.md**: Sync pipeline and background worker resilience.
