# Release Checklist

## Before tagging

- [ ] `pyproject.toml` version updated.
- [ ] `CHANGELOG.md` updated.
- [ ] Local smoke test passed (`webmail-summary serve`).
- [ ] No secrets in repo.

## Release execution

- [ ] Create tag: `vX.Y.Z`.
- [ ] Push tag to GitHub.
- [ ] Confirm GitHub Action `Release` completed.
- [ ] Verify attached assets:
  - `webmail-summary.exe`
  - `webmail-summary-windows-x64.zip`
  - `SHA256SUMS.txt`

## Post release

- [ ] Download asset from release page and run smoke test on clean Windows VM.
- [ ] Verify update-check UI detects latest version.
- [ ] Monitor bug reports for first 48 hours.
