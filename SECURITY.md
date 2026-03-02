# Security Policy

## Supported Versions

Security updates are currently provided for the latest release line only.

## Reporting a Vulnerability

If you discover a security issue, please do not open a public issue first.

- Contact: create a private report via repository security advisory if enabled.
- If private advisory is not available, open an issue with minimal details and request private follow-up.

Please include:

- Affected version
- Reproduction steps
- Impact scope (data exposure, privilege escalation, etc.)
- Suggested mitigation (if known)

## Security Notes for This Project

- API keys should be stored in Windows Credential Manager through keyring, not in SQLite.
- Mail data is stored locally under the app data directory.
- When cloud LLM is enabled, summary payloads are sent to the configured provider API.
