# Changelog

All notable changes to this project are documented in this file.

## [0.5.11] - 2026-03-10

### Changed

- 앱 아이콘 자산을 하나로 통일해 브라우저 탭 아이콘과 앱 실행 아이콘의 일관성을 개선.

## [0.5.10] - 2026-03-07

### Fixed

- 업데이트 버튼이 `SHA256SUMS.txt`를 여는 문제를 수정하고, OS별 설치 파일을 우선 선택하도록 개선.
- 설치본(Windows exe)에서 동기화 시작 시 `sync worker failed: exit 2`로 실패하던 워커 실행 경로를 수정.

## [0.5.6] - 2026-03-03

### Added

- 앱 시작 시 업데이트 안내 팝업(지금 업데이트/나중에/오늘 하루/1주일/이 버전 건너뛰기).

### Changed

- Windows 배포 exe 실행 시 콘솔 창이 뜨지 않도록 빌드 옵션 변경(PyInstaller `--noconsole`).

### Fixed

- /setup IMAP 연결 테스트에서 422가 발생하던 문제를 완화하고, 비밀번호 오류/네트워크 오류를 구분해 안내.

## [0.5.7] - 2026-03-03

### Fixed

- SignPath 서명 단계가 실패해도 릴리즈 빌드가 실패하지 않도록 워크플로를 개선(서명은 선택 사항).

## [0.5.8] - 2026-03-03

### Fixed

- Windows 배포(no-console) 실행 시 Uvicorn 로깅 설정에서 크래시 나던 문제를 수정.

## [0.5.9] - 2026-03-03

### Changed

- Windows에서 동기화/로컬 LLM 백그라운드 프로세스 실행 시 콘솔 창이 뜨지 않도록 프로세스 시작 플래그를 보강.

### Fixed

- 동기화 시작 전 LLM 준비 상태를 사전 점검하고, 사용자에게 원인(엔진 미설치/모델 미설치 등)을 즉시 안내.

## [0.5.5] - 2026-03-02

### Fixed

- GitHub Actions 릴리즈 워크플로에서 SignPath 시크릿 유무에 따라 조건부 실행이 실패하던 문제를 수정.

## [0.5.4] - 2026-03-02

### Added

- SignPath Foundation 온보딩 문서 및 코드서명 정책/프라이버시 문서.
- 릴리즈 워크플로에 SignPath 서명(옵션) 단계 추가.

## [0.5.3] - 2026-03-02

### Fixed

- Frozen(배포 exe) 실행에서 앱 버전이 0.0.0으로 표시되던 문제를 수정.

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
