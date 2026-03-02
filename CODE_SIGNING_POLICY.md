# Code signing policy

Free code signing provided by SignPath.io, certificate by SignPath Foundation

This project distributes Windows executables via GitHub Releases.

## Roles

- Committers & reviewers: Kyungchan Choi (https://github.com/repairer5812)
- Approvers (SignPath signing requests): Kyungchan Choi (https://github.com/repairer5812)

## What we sign

- `webmail-summary.exe` (portable)
- `webmail-summary-setup-windows-x64.exe` (installer)

## How signing works

- Release artifacts are built from source by GitHub Actions on GitHub-hosted runners.
- Unsigned artifacts are uploaded as a GitHub Actions artifact.
- A SignPath signing request is submitted and requires manual approval (SignPath Foundation policy).
- After approval, SignPath returns signed artifacts.
- The workflow publishes the signed artifacts to GitHub Releases and regenerates `SHA256SUMS.txt`.

## Privacy policy

See `PRIVACY.md`.
