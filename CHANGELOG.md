# Changelog

All notable changes to this project are documented in this file.

## [0.5.3] - 2026-03-02

### Fixed

- Frozen(배포 exe) 실행에서 앱 버전이 0.0.0으로 표시되던 문제를 수정.

## [0.5.4] - 2026-03-02

### Added

- SignPath Foundation 온보딩 문서 및 코드서명 정책/프라이버시 문서.
- 릴리즈 워크플로에 SignPath 서명(옵션) 단계 추가.

## [0.5.2] - 2026-03-02

### Added

- Windows installer build (Inno Setup) in release workflow.
- Installer script for per-user install with Start Menu/Desktop shortcuts.

### Changed

- CLI default now launches `serve` when no subcommand is provided.
- Landing screenshot section improved readability (larger previews, no cropping, open original).

## [0.5.0] - 2026-03-02

### Added

- Dashboard update management UI and actions.
- GitHub Releases update check flow (manual + scheduled checks).
- Update controls: snooze 1 week and skip selected version.

### Changed

- Summary section naming unified to `핵심 요약` / `상세 요약`.
- Summary formatting made more robust across short and long mail paths.
- Dashboard day-card summary highlight behavior adjusted (removed colon-prefix accenting).
- App version bumped to `0.5.0`.

### Fixed

- Message detail summary area rendering issue caused by stale inline script fragment.
