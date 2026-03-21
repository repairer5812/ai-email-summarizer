# Changelog

All notable changes to this project are documented in this file.

## [0.5.41] - 2026-03-21

### Fixed

- 날짜 화면 상단 액션 버튼이 화면 폭에 따라 세로로 흩어지지 않도록, 버튼 영역을 한 줄 툴바 형태로 고정했습니다.
- 로컬 llama-server 요약이 오래 걸리는 환경에서 timeout 가능성을 낮추도록 요청 timeout/예산을 추가 상향하고, timeout 시 1회 재시도 시 입력을 더 줄여 빠르게 복구하도록 개선했습니다.

## [0.5.40] - 2026-03-21

### Fixed

- 로컬 llama-server 요약이 자주 timeout으로 끝나던 문제를 완화했습니다.
  - 요청 timeout/총 예산을 상향하고, timeout 시 로컬 서버를 재시작한 뒤 1회 재시도합니다.
- 동기화/날짜별 재요약의 LLM hard timeout을 상향해, 느린 PC에서도 요약이 중간에 끊기지 않도록 했습니다.

## [0.5.39] - 2026-03-21

### Fixed

- 업데이트 후에도 버튼 레이아웃이 구버전 CSS 캐시 때문에 계속 깨져 보일 수 있어, 정적 리소스(app.css/app.js)에 버전 기반 캐시 무효화(query string)를 적용했습니다.
- 날짜 화면 우측 액션 버튼이 매우 좁은 폭에서 1개씩 줄바꿈되며 세로로 쌓이던 현상을 완화했습니다.
  - 버튼 그룹을 기본적으로 nowrap + 가로 스크롤 가능하게 처리해, 최소한 "가로 정렬"을 유지합니다.

## [0.5.38] - 2026-03-21

### Fixed

- 날짜 화면 우측 액션 버튼이 창 폭에 따라 1개씩 줄바꿈되며 세로로 쌓이던 문제를 개선했습니다.
  - 버튼 그룹이 필요 시 다음 줄로 내려가더라도, 버튼은 가급적 가로 한 줄로 유지되도록 레이아웃을 보강했습니다.
- 날짜별 재요약에서 LLM 호출 중 진행률 콜백이 오지 않는 동안 UI가 멈춘 것처럼 보이던 문제를 완화했습니다.
  - LLM 처리 중 경과 시간을 주기적으로 업데이트하는 heartbeat를 추가했습니다.

### Changed

- 본문 가독성을 위해 기본 글자 크기를 소폭 키웠습니다. (모바일/좁은 화면에서는 증가폭을 낮춤)

## [0.5.37] - 2026-03-21

### Changed

- 문서/랜딩 페이지에 IMAP 기반으로 다양한 메일 서비스에서 사용할 수 있음을 명시했습니다.
  - Daouoffice 전용이 아니라, IMAP을 제공하는 메일 서비스(Gmail/Google Workspace 등)에도 적용 가능합니다.
- 폴더 선택(가져올 메일 폴더를 고르는 기능)이 가능함을 안내 문구로 보강했습니다.

## [0.5.36] - 2026-03-21

### Fixed

- 날짜 화면 우측 액션 버튼이 세로로 쌓이던 레이아웃을 가로 배치로 고정했습니다.
- 메일 상세/날짜별 요약에서 요약 텍스트가 JS 포맷팅 실패 시에도 안전하게 표시되도록 fallback을 추가했습니다.
- `(LLM timeout)` 발생 빈도를 줄이기 위해 로컬/클라우드 요약 hard timeout을 상향하고, "오류/누락만 다시 요약" 대상에 timeout 결과도 포함했습니다.

### Changed

- 랜딩 페이지 스크린샷 섹션을 1열(세로 스택)로 변경해 이미지가 눌리지 않도록 조정했습니다.
- GitHub Actions(Pages/landing CI)를 Node 24 런타임 전환에 맞춰 업데이트했습니다.

## [0.5.35] - 2026-03-21

### Added

- OpenRouter 모델 목록을 실시간으로 불러와 선택할 수 있게 했습니다.
  - `/api/openrouter/models`로 모델 목록을 가져오며, OpenRouter API Key가 설정되어 있으면 주기적으로 갱신합니다.
  - 키가 없거나 네트워크가 불안정한 경우에는 캐시/기본 목록으로 동작합니다.
- 모델 선택 UI에 검색 입력을 추가했습니다.
  - OpenRouter 선택 시 "모델 검색"에 몇 글자 입력하면 목록이 자동 필터링됩니다.

## [0.5.34] - 2026-03-21

### Fixed

- 업데이트 후 실제 설치는 `0.5.33`으로 완료되었는데 UI가 `0.5.32`로 표시되던 버전 인식 오류를 수정했습니다.
  - Windows 설치형(frozen) 실행에서 패키지 fallback 대신 현재 실행 중 EXE의 파일 버전(ProductVersion/FileVersion)을 우선 읽도록 보강.
  - 버전 조회 시 경로 문자열 삽입 대신 환경변수를 통해 안전하게 전달해 경로 파싱 실패 가능성을 낮춤.

## [0.5.33] - 2026-03-21

### Fixed

- 자동 업데이트 후 앱이 이전 버전으로 다시 실행되는 경로를 보강했습니다.
  - 재실행 대상 실행파일을 설치 경로(`%LOCALAPPDATA%\\Programs\\webmail-summary\\webmail-summary.exe`) 우선으로 선택하도록 수정.
  - 자동 적용 시 설치형 `setup` 자산이 아닌 포터블 `webmail-summary.exe`는 차단해 잘못된 업데이트 실행을 방지.
  - 설치 완료 후 대상 실행파일의 버전을 확인해 기대 버전과 불일치하면 오류로 처리하도록 검증을 추가.

### Changed

- 로컬 모델 기본 옵션을 재배치했습니다.
  - `빠름(fast)`을 EXAONE 3.5 2.4B로 변경.
  - `표준(standard)`을 Gemma 3 4B로 변경.
  - 기본 추천 모델은 `fast`를 유지하므로 신규 사용자 기본은 EXAONE 빠름 모드입니다.

## [0.5.32] - 2026-03-21

### Fixed

- 동기화가 `running` 상태에서 `1/N`에 장시간 머무르던 정체 케이스를 보강했습니다.
  - LLM timeout 이후 heartbeat/worker 정리 경로를 강화해 다음 단계 진행이 멈추지 않도록 수정.
  - timeout 이후 서버 정지 호출을 bounded wait로 감싸 장시간 블로킹 가능성을 낮춤.
- stale sync 잡 회복 로직을 개선했습니다.
  - `queued/running/cancel_requested` 상태의 장기 정체 잡을 자동 감지해 재시도 가능한 상태로 회복.
  - sync worker 종료 직후 최신 DB 상태를 재조회해 `exit 15`가 최종 상태를 덮어쓰는 race를 완화.

## [0.5.31] - 2026-03-21

### Fixed

- 자동 업데이트 핸드오프 안정성을 보강했습니다.
  - 상태 파일 파싱을 `utf-8-sig`로 통일해 BOM 포함 JSON에서도 중간 종료로 오판하지 않도록 수정.
  - PowerShell 스크립트의 `$Pid` 자동 변수 충돌을 피하도록 파라미터명을 `$TargetPid`로 변경.
- 앱 종료 경로를 강제 종료 우선에서 graceful 종료 우선으로 조정했습니다.
  - 네이티브 윈도우/서버 종료에서 유예 대기 후 bounded fallback 강제 종료로 전환해 잔류 프로세스 및 `_MEI` 정리 경고 가능성을 완화.
- 설정 화면에서 IMAP 비밀번호 저장 상태 표시 로직의 중복 블록을 제거해 상태 판정이 일관되게 동작하도록 정리했습니다.

### Changed

- UI 테마를 `Bento Grid`와 `Soft 3D (Clay)`로 전환했습니다.
  - 기존 `trust/creative` 값은 `bento/clay`로 자동 정규화되어 기존 사용자 설정이 유지됩니다.
  - 설정 화면 테마 선택/라벨/저장 경로를 새 테마 키에 맞게 정리했습니다.

## [0.5.30] - 2026-03-20

### Fixed

- 요약 단계 단건 지연/정체에 대해 워커 레벨 안전장치를 추가했습니다.
  - `sync`/`resummarize` 작업에서 LLM 호출을 별도 스레드로 실행하고 hard deadline(기본 75s, cloud 120s)을 초과하면 timeout 요약으로 즉시 다음 메일로 진행.
  - timeout/예외 발생 시 이벤트 로그를 남기고 local llama-server를 강제 정리해 같은 잡에서 반복 정체가 누적되지 않도록 보강.
- local llama-server 지연 상한을 추가로 단축했습니다.
  - fast/standard tier 요청 timeout/토큰 상한을 재조정하고 재시도 횟수 및 총 예산을 축소해 장시간 대기를 줄임.

## [0.5.29] - 2026-03-20

### Fixed

- 자동 업데이트에서 "핸드오프 프로세스가 즉시 종료" 오류가 발생하던 문제를 수정했습니다.
  - Windows PowerShell 런처의 생성 플래그를 조정해(`CREATE_NO_WINDOW` 중심) 프로세스가 즉시 종료되는 케이스를 제거.
  - updater 스크립트를 `utf-8-sig`로 저장하고 상태 메시지를 ASCII로 통일해 인코딩 파싱 오류로 조기 종료되는 문제를 방지.

## [0.5.28] - 2026-03-20

### Fixed

- 단일 메일 요약이 장시간 멈춘 것처럼 보이는 현상을 추가 완화했습니다.
  - local llama-server 경로의 생성 토큰 상한과 요청 timeout을 더 낮춰 장시간 대기 구간을 단축.
  - llama HTTP 호출에 하드 대기 상한을 추가하고, timeout 발생 시 서버 재기동 후 제한 횟수 내에서만 재시도하도록 보강.
  - 전체 요청 예산(`total_request_budget_s`)을 축소해 1건 요약이 수분 단위로 붙잡히는 상황을 줄임.

## [0.5.27] - 2026-03-20

### Fixed

- `v0.5.26` 릴리즈 워크플로의 `Build installer` 단계 실패를 수정했습니다.
  - Inno `[Setup]` 지시어를 `CloseApplications=force`로 교정하고, 유효하지 않은 지시어(`ForceCloseApplications`)를 제거.
  - 자동 업데이트 런타임 인자의 `/FORCECLOSEAPPLICATIONS`는 유지하여 설치 중 프로세스 잠금 완화 동작은 계속 적용.

## [0.5.26] - 2026-03-20

### Fixed

- 자동 업데이트 설치 중 "모든 응용 프로그램을 자동으로 닫지 못했습니다" 팝업이 뜨며 멈추는 문제를 완화했습니다.
  - 업데이터 스크립트에서 `webmail-summary`/`llama-server` 프로세스를 설치 직전 선제 종료.
  - Inno 실행 인자에 `/FORCECLOSEAPPLICATIONS`, `/LOGCLOSEAPPLICATIONS`를 추가해 잠금 파일 종료를 강화.
  - 설치기 기본 설정(`.iss`)에 `CloseApplications=yes`, `ForceCloseApplications=yes`, `RestartApplications=no`를 반영.
- 단일 메일 요약이 장시간(수분) 머무르는 문제를 완화했습니다.
  - local llama-server 표준/빠름 tier의 `max_tokens` 및 요청 timeout을 축소해 장기 대기를 제한.
  - llama-server provider에 전체 요청 예산(`total_request_budget_s`)과 재시도 횟수 상한을 추가.
  - fast tier 장문 요약에서 합성(synthesis) 단계를 생략하고, standard/fast chunk 임계값을 지연시간 우선으로 재조정.

## [0.5.25] - 2026-03-20

### Fixed

- 자동 업데이트에서 설치가 실제로 시작되지 않았는데도 앱이 종료되어, 재실행 후 다시 업데이트를 요구하던 문제를 보강했습니다.
  - 업데이트 핸드오프 스크립트에 상태 파일(`apply_update_status.json`) 기록을 추가하고, 서버가 해당 상태를 확인한 뒤에만 종료하도록 변경.
  - 설치 파일 존재 확인/실행 예외를 명시적으로 실패 처리해, 조기 종료를 성공으로 오인하지 않도록 수정.
  - Windows 릴리즈 자산 선택에서 `webmail-summary.exe`(포터블) 우선 선택 위험을 낮추고 설치형(`setup`/`installer`) 자산 가중치를 강화.
  - Inno 설치 실행 인자에 `/CLOSEAPPLICATIONS`를 추가해 실행 중 프로세스로 인한 무효 설치 가능성을 완화.

## [0.5.24] - 2026-03-20

### Fixed

- 짧은 결재/알림 메일이 요약 단계에서 장시간 머무르는 문제를 완화했습니다.
  - HTML fallback 요약 입력에서 숨김 영역/인용 블록(`blockquote`, `gmail_quote` 등)을 제거해 본문 길이 과대 추출을 줄임.
  - 회신 체인 헤더(영문/국문) 이후 내용을 잘라내고 공백 정규화 + 길이 상한을 적용해 불필요한 LLM 호출을 줄임.
- 앱 종료 시 간헐적으로 검은 CMD 창이 잠깐 뜨는 문제를 줄였습니다.
  - Windows에서 `taskkill`/`schtasks` 호출을 `CREATE_NO_WINDOW` + 숨김 startup info로 실행하도록 통일.

## [0.5.23] - 2026-03-20

### Fixed

- 자동 업데이트 다운로드 완료 후 앱이 종료되지만 설치가 시작되지 않는 경우에도 앱이 무조건 종료되던 문제를 수정했습니다.
  - 업데이트 핸드오프(PowerShell) 프로세스가 정상 시작된 경우에만 앱을 종료하도록 변경.
  - `powershell.exe` 경로를 명시적으로 해석해 실행 실패 가능성을 줄이고, 즉시 종료 시 사용자에게 오류를 표시하도록 개선.

## [0.5.22] - 2026-03-16

### Changed

- 로컬 `fast` 요약 경로를 지연시간 우선으로 재튜닝해 1건 처리 시간이 길어지는 체감을 줄였습니다.
  - fast tier의 llama-server 요청 타임아웃을 단축하고 생성 토큰 수를 추가로 축소.
  - 장문 메일 요약 시 fast tier의 청크/합성 전략을 간소화해 호출 횟수를 줄임.

### Fixed

- 동기화 중 heartbeat 진행 갱신이 실제 진행값을 되돌려 보이는 경우가 있어, 기존 진행값보다 뒤로 가지 않도록 보정했습니다.
- 트레이 `프로그램 종료` 시 `webmail-summary` 서버 프로세스가 종료되지 않던 문제를 수정했습니다.
  - `/lifecycle/request-exit` 경로를 실제 종료 루트로 연결하고 종료 직전에 탭 종료 신호를 기록.
  - 앱 강제 종료 경로에서 llama-server 정리 시 in-flight 조건과 무관하게 종료하도록 `force` 종료를 적용.

## [0.5.18] - 2026-03-15

### Fixed

- 로컬 요약(요약 중) 단계에서 장시간 진행될 때도 진행 메시지가 주기적으로 갱신되도록 개선.
- llama-server 유휴 종료 타이머가 추론 중 서버를 중단하지 않도록 보호하고, 느린 환경에서 타임아웃/유휴 시간을 완화.
- fast 로컬 모델에서 생성 토큰 수를 줄여(속도 우선) 요약 지연을 완화.
- 트레이 아이콘 더블클릭 시 창이 다시 표시되도록 기본 동작을 지정.

## [0.5.19] - 2026-03-15

### Fixed

- 독립 창(UI) 실행 시 로컬 서버 준비가 느리거나 `active_url.txt`가 stale 상태일 때 예외로 종료되지 않도록 개선(재시도/대기 증가 + 오류 안내 메시지).

## [0.5.20] - 2026-03-15

### Fixed

- Windows 설치본에서 업데이트/클라우드 호출 시 TLS CA 번들(certifi) 경로 오류로 HTTPS 요청이 실패하던 문제를 수정.
  - 릴리즈 빌드에서 `certifi` CA 파일을 명시적으로 포함.
  - 런타임에서 `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`을 best-effort로 설정.

## [0.5.21] - 2026-03-15

### Fixed

- 이전 실행에서 상속된 stale `_MEI...\certifi\cacert.pem` 환경변수 경로가 남아 TLS가 다시 실패하던 케이스를 추가로 수정.
  - `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`이 유효하지 않으면 현재 실행의 유효한 certifi 경로로 강제 교정.

## [0.5.17] - 2026-03-15

### Added

- 브라우저 대신 독립 앱 창(pywebview)으로 실행되는 UI 모드 추가.
- 창 닫기 시 트레이로 최소화되고, 트레이 메뉴(열기/종료)로 제어 가능.
- 자동 업데이트 진행률 표시(다운로드 %/단계 메시지) 추가.

### Changed

- 자동 업데이트 후 재실행 대상을 조정해(dev 환경에서도 설치본 실행), 업데이트 테스트가 혼동되지 않도록 개선.
- 동기화 시작 전 LLM 준비 상태를 더 명확히 검사하고(로컬/클라우드), 원인을 즉시 안내.

### Fixed

- llama.cpp 서버가 유휴 상태로 오래 떠 있는 경우를 줄이기 위해 idle 자동 종료(타이머) 추가.

## [0.5.14] - 2026-03-12

### Fixed

- 앱 버전 계산 순서를 조정해 패키지 메타데이터 버전이 있을 때 `_version.txt`의 기본값(`0.0.0`)에 가려지지 않도록 수정.

### Changed

- GitHub Actions 워크플로 액션 버전을 Node 24 런타임 대응 버전(`checkout/setup-python/setup-node/upload-artifact`)으로 업데이트.

## [0.5.13] - 2026-03-12

### Changed

- 로컬 AI 기본 모델 기본값을 `표준`에서 `빠름`으로 조정.
- `빠름` 프리셋 모델을 `Gemma 2 2B`에서 `Gemma 3 4B (Q4_K_M)`로 업데이트.
- OpenRouter 모델 선택 목록에 Gemma 3 (4B/12B/27B) 옵션을 추가.

## [0.5.12] - 2026-03-10

### Changed

- Windows 설치 파일 이름에 버전(`vX.Y.Z`)이 포함되도록 릴리즈 산출물 명명 규칙을 개선.
- 설치 시 실행 중인 `webmail-summary` 프로세스를 자동/강제 종료하도록 인스톨러 동작을 강화.
- 추가 작업의 바탕화면 바로가기 체크 상태가 기본 선택되도록 설치 옵션을 고정.

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
