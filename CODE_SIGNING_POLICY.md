# Code signing policy

The Windows executables published in this project's GitHub Releases are currently **not code-signed**.

An application to SignPath Foundation (free OSS code signing) was submitted but **not approved**, so release artifacts are published unsigned. Windows SmartScreen may therefore warn on first run. See the "설치 중 Windows 보안 경고가 뜨면" section of `README.md` for how to proceed.

## How releases are produced

- Release artifacts are built from public source by GitHub Actions on GitHub-hosted runners (no manual uploads).
- Each release includes `SHA256SUMS.txt` so users can verify the integrity of downloaded files.

## Roles

- Maintainer: Kyungchan Choi (https://github.com/repairer5812)

## Privacy policy

See `PRIVACY.md`.
