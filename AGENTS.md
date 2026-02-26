# PROJECT KNOWLEDGE BASE (webmail_summary)

**Generated:** 2026-02-24
**Commit:** b6acb4a
**Branch:** main

## OVERVIEW
Local-first mail archiving, LLM-based summarization (llama.cpp/OpenRouter), and Obsidian export. Built with Python 3.10+, FastAPI, IMAPClient, and SQLite.

## STRUCTURE
```
webmail_summary/
├── src/webmail_summary/
│   ├── app/          # FastAPI application & entry
│   ├── api/          # REST API endpoints
│   ├── ui/           # Jinja2 templates & web routes
│   ├── llm/          # LLM providers & local engine
│   ├── jobs/         # Background sync/process workers
│   ├── archive/      # EML parsing & sanitization
│   └── index/        # SQLite DB & mail repo
└── run_dev.ps1       # Dev environment setup
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Startup | src/webmail_summary/cli.py | CLI commands (serve, sync) |
| Web Server | src/webmail_summary/app/main.py | FastAPI & server lifecycle |
| DB Schema | src/webmail_summary/index/db.py | SQLite tables & migrations |
| LLM Logic | src/webmail_summary/llm/ | Local GGUF & OpenRouter |
| Job Runner | src/webmail_summary/jobs/runner.py | Background task orchestration |

## ARCHITECTURE GUIDELINES
- **Storage**: Mail metadata in SQLite; raw .eml and attachments in local file system.
- **Security**: NEVER store API keys in SQLite. Use `keyring` (Windows Credential Manager).
- **Processing**: Mark mail as \Seen on IMAP server ONLY after successful local archive and index.
- **HTML Handling**: Rewrite cid: and download/rewrite external assets to local paths.
- **LLM Cleanup**: Strip common noise (footer, legal disclaimers) before summarization.

## DEVELOPMENT COMMANDS
```powershell
# Setup environment
.\run_dev.ps1

# Start server
webmail-summary serve
```

## ANTI-PATTERNS
- **Secrets in DB**: Always use keyring for sensitive tokens.
- **Image Proxy**: Download assets locally; don't rely on server-side optimization.
- **Raw LLM Noise**: Summaries must be concise and free of legal/technical footers.

## DOCUMENTATION HIERARCHY
- **./AGENTS.md**: Root overview and project rules.
- **src/webmail_summary/AGENTS.md**: Core package structure and entry points.
- **src/webmail_summary/llm/AGENTS.md**: LLM provider logic and noise removal.
- **src/webmail_summary/ui/AGENTS.md**: Templates, static assets, and i18n.
- **src/webmail_summary/jobs/AGENTS.md**: Sync pipeline and background worker resilience.
