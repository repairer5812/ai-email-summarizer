# SignPath Foundation (OSS) code signing

This repo is distributed as Windows executables. Unsigned executables often trigger Windows SmartScreen ("Windows PC protected").

To reduce these warnings, we can sign release artifacts through SignPath Foundation (free for eligible open source projects).

## What gets signed

- `webmail-summary.exe` (portable)
- `webmail-summary-setup-windows-x64.exe` (installer)

The release workflow will then re-generate:

- `webmail-summary-windows-x64.zip` (zip of the signed portable exe)
- `SHA256SUMS.txt` (hashes of the signed assets)

## Requirements (high level)

- OSI-approved license for all components (this repo is MIT licensed).
- No proprietary / closed-source components checked into the repo.
- Project is actively maintained.
- SignPath GitHub integration uses GitHub-hosted runners for OSS projects.

SignPath Foundation overview:

- https://signpath.org/

## SignPath setup

1) Apply for SignPath Foundation

- Apply: https://signpath.org/

2) In SignPath (SignPath.io), create an Organization + Project

3) Add Trusted Build System: GitHub.com

- Docs: https://docs.signpath.io/trusted-build-systems/github

4) Install the SignPath GitHub App (recommended)

- App: https://github.com/apps/signpath

5) Configure Signing Policy and Artifact Configuration

Important: GitHub workflow artifacts are submitted as ZIP archives.
Artifact Configuration should use `<zip-file>` as the root element.

## GitHub repository configuration

Add the following:

GitHub Secrets
- `SIGNPATH_API_TOKEN`: API token for a SignPath user who has submitter permissions.

GitHub Variables
- `SIGNPATH_ORGANIZATION_ID`: your SignPath organization ID
- `SIGNPATH_PROJECT_SLUG`: project slug
- `SIGNPATH_SIGNING_POLICY_SLUG`: signing policy slug (e.g. `release-signing`)
- Optional: `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`

## Workflow integration

We use SignPath's official GitHub Action:

- https://github.com/SignPath/github-action-submit-signing-request

The release workflow is set up so that signing is optional:

- If `SIGNPATH_API_TOKEN` is present, the workflow submits a signing request and uses the signed exes.
- If not present, it publishes unsigned artifacts (useful while onboarding).

## Notes

- SignPath Foundation may require manual approval before signing completes.
- Once signing is enabled, the Windows "PC protected" prompt should be significantly reduced over time.
