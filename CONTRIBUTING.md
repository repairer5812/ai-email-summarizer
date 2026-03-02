# Contributing

Thanks for considering a contribution.

## Development Setup

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -U pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt
& ".\.venv\Scripts\pip.exe" install -e .
```

Run app locally:

```powershell
& ".\.venv\Scripts\webmail-summary.exe" serve
```

## Pull Request Guidelines

- Keep changes scoped and atomic.
- Follow existing project patterns in `src/webmail_summary`.
- Do not store secrets in code or SQLite.
- Update `CHANGELOG.md` for user-facing changes.
- Include clear reproduction and verification steps in PR description.

## Issue Reporting

When opening issues, include:

- App version
- Windows version
- Steps to reproduce
- Expected vs actual behavior
- Logs/screenshots where applicable
