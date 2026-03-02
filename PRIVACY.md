# Privacy policy

webmail-summary is a local-first mail archiving and summarization tool.

## What data is stored locally

- Mail metadata: stored locally in SQLite.
- Raw emails (.eml) and attachments: stored locally on disk.
- API keys: stored in Windows Credential Manager via `keyring` (not in the database).

## Network connections

The program only connects to network systems that are required for the features you enable:

- IMAP server: the mail server you configure.
- Optional LLM provider: if you enable a cloud provider (for example OpenRouter), email content is sent to that provider to generate summaries.
- Optional downloads: if you choose to download external assets referenced by emails (for example images), the program may request those URLs.

We do not run analytics or telemetry by default.

## Uninstallation

If you install using the Windows installer, it provides an uninstaller.
