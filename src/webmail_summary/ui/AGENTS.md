# AGENTS.md | UI/Templates

## Meta Context
- **Role**: UI/Templates Specialist
- **Directory**: `src/webmail_summary/ui`
- **Tech Stack**: FastAPI, Jinja2, Semantic HTML, CSS, i18n (ko/en)

## Core Principles
- **Local-First**: No external CDN dependencies for CSS/JS. Assets must be in `static/`.
- **Semantic HTML**: Prioritize readability and clean structure in templates.
- **Theming**: Support the "bento" and "clay" themes via CSS variables (legacy "trust"/"creative" settings map to them).
- **I18n**: All UI strings must use the `t(request, key)` helper from `i18n.py`.

## Template Architecture
- `templates/base.html`: Main layout, including header, footer, and theme injection.
- `templates/home.html`: Dashboard with sync status and daily email cards.
- `templates/setup.html`: Multi-tab configuration wizard for IMAP, AI, and Profile.
- `templates/day.html` & `templates/message_detail.html`: Mail viewing components.

## Static Assets
- `static/app.css`: Central styles. Use CSS variables for theme-specific colors.
- `static/favicon.svg`: Vector icon source.
- **Favicon**: `/favicon.ico` redirects to `static/app-icon.png` (see `app/main.py`). The tray icon is embedded as base64 in `tray_icon_data.py`.

## Windows Launcher and Updater
- `native_window.py`: starts the server child, opens the pywebview (WebView2) window, retries once, then falls back to the browser and a pystray fallback tray. Windows only; other platforms run `serve()` in browser mode.
- `updates.py`: GitHub release check and in-app update. It copies `resources/apply_update.ps1` next to the downloaded installer and runs it with `powershell -File`. Keep `resources/` in the PyInstaller `--add-data` list and in pyproject package-data.

## Dev Guidelines
- **No JS Frameworks**: Use vanilla JS or lightweight patterns for interactivity (e.g., sync progress polling).
- **Time Formatting**: Use `timefmt.py` to ensure consistent KST display.
- **Icon Strategy**: Prefer SVG or Unicode symbols to keep the binary small.
- **FastAPI Injection**: `templates.env.globals["t"] = _t` makes the translator available in all Jinja2 scopes.

## Anti-Patterns
- Hardcoding strings in templates (use `i18n.py`).
- Relative paths for static assets in templates (use `url_for('static', path=...)`).
- Bloated CSS; keep `app.css` focused and modular.
