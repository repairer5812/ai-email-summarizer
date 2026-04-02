# macOS Support Plan

This project is currently Windows-first in its packaged app experience, but most core mail/LLM/export logic is already portable.

## Current Support Boundary

- Core logic is Python + FastAPI + SQLite and is largely cross-platform.
- Windows-specific areas still block a polished macOS release:
  - native desktop wrapper behavior
  - installer/update apply flow
  - startup-on-login task integration
  - local llama.cpp asset selection and packaging
  - release pipeline/signing/notarization

## Stage 1: Safe Preparation (done or ready)

- Make app-data paths platform aware.
- Prefer macOS-friendly defaults for user-visible storage paths.
- Remove `.exe` assumptions from local llama server discovery.
- Generalize llama.cpp asset picking by OS/architecture.

These changes reduce Windows coupling without requiring a Mac to validate.

## Stage 2: Browser-Mode macOS Support

Goal: allow reliable source-run/browser-based usage on macOS before native app parity.

Needed work:

- audit any remaining Windows-only code executed during `serve`
- verify keyring behavior against macOS Keychain prompts
- verify local llama.cpp install/download path on macOS
- confirm local browser launch / localhost UX

## Stage 3: Native macOS App Support

Goal: deliver a macOS app bundle with a local webview wrapper.

Needed work:

- choose wrapper strategy (`pywebview` parity vs separate macOS wrapper path)
- replace Windows-only process flags and UI close behavior with macOS-safe flow
- ensure single-instance + bring-to-front behavior works on macOS
- decide whether first release will be browser-only or embedded webview

## Stage 4: Packaging and Updates

Needed work:

- create macOS build artifacts (`.app`, `.dmg`, or equivalent)
- add Developer ID signing and notarization pipeline
- design a macOS-specific update path (Windows PowerShell/Inno Setup flow is not reusable)

## Known High-Risk Files

- `src/webmail_summary/ui/updates.py`
- `src/webmail_summary/ui/native_window.py`
- `src/webmail_summary/startup_task.py`
- `src/webmail_summary/llm/local_engine.py`
- `.github/workflows/release.yml`
- `installer/webmail-summary.iss`

## Recommendation

Ship macOS in two steps:

1. source/browser-mode support first
2. native app packaging second

This keeps the risk manageable when no Mac is available for immediate hands-on testing.
