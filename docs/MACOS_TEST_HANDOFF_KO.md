# macOS 테스트 전달용 가이드

이 문서는 실제 Mac 장비를 가진 테스트 담당자에게 그대로 전달할 수 있는 실행 가이드입니다.

## 테스트 목적

현재 이 프로젝트는 macOS에서 먼저 **browser-mode** 기준으로 검증합니다.

즉,

- Windows처럼 설치형 앱/네이티브 창 검증이 아니라
- 로컬 FastAPI 서버를 띄우고
- 브라우저에서 UI를 열어
- setup / sync / summary / export / daily overview가 정상 동작하는지 확인하는 단계입니다.

## 준비물

- 다운로드할 파일:
  - 현재는 macOS 전용 설치 파일이 없으므로, **GitHub 릴리즈의 `Source code (zip)` 또는 `Source code (tar.gz)`** 를 받아야 합니다.
  - 권장 다운로드:
    - `https://github.com/repairer5812/ai-email-summarizer/archive/refs/tags/v0.6.1.zip`
    - `https://github.com/repairer5812/ai-email-summarizer/archive/refs/tags/v0.6.1.tar.gz`
  - 또는 git 사용 가능하면:

```bash
git clone https://github.com/repairer5812/ai-email-summarizer.git
```

- 주의: 아래 파일들은 **Windows용** 이므로 macOS 테스트에 사용하면 안 됩니다.
  - `webmail-summary-setup-windows-x64-vX.Y.Z.exe`
  - `webmail-summary.exe`
  - `webmail-summary-windows-x64.zip`

- Python 3.10 이상
- 테스트용 IMAP 계정
- 가능하면 cloud API key 1개
- Obsidian vault로 사용할 빈 폴더 1개

## 실행 순서

프로젝트 폴더에서 아래 순서대로 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m webmail_summary serve
```

브라우저가 자동으로 열리지 않으면, 터미널에 나온 `http://127.0.0.1:<port>/` 주소를 직접 열어주세요.

## 테스트 순서

아래 순서대로 확인해주세요.

1. 앱 첫 화면이 정상적으로 열리는지
2. `/setup`에서 설정 저장이 되는지
3. cloud API key 저장/테스트가 되는지
4. IMAP 테스트가 되는지
5. sync 1회 실행 시
   - 메일을 가져오는지
   - 개별 메일 요약이 되는지
   - `daily_overview`가 갱신되는지
   - Obsidian export가 생성되는지
6. 앱 종료 후 다시 실행했을 때 정상 접근되는지
7. 가능하면 local LLM도 확인
   - llama.cpp asset 선택이 맞는지
   - 실제 실행 가능한지

## 특히 확인해야 할 문제

- macOS Keychain prompt가 비정상적으로 반복되는지
- localhost 접속이 막히는지
- local llama.cpp 실행 시 Gatekeeper / quarantine 문제 있는지
- sync 후 `daily_overview`가 생성되지 않는지
- 종료 후 재실행 시 포트/프로세스가 꼬이는지

## 같이 전달받아야 할 정보

- Mac 모델
- CPU 아키텍처 (`arm64` / `x86_64`)
- macOS 버전
- Python 버전
- 성공/실패 여부
- 실패한 단계
- 터미널 출력
- 스크린샷
- 가능하면 `server.log`

## 짧은 전달용 버전

```text
macOS에서는 설치형이 아니라 browser-mode로 테스트해주세요.

실행:
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m webmail_summary serve

확인할 것:
1) 앱 열림
2) setup 저장
3) cloud key 테스트
4) IMAP 테스트
5) sync
6) 메일 요약
7) daily_overview 생성
8) Obsidian export
9) 종료 후 재실행
10) 가능하면 local llama.cpp 실행

같이 보내줄 것:
- Mac 모델 / arm64 or x86_64
- macOS 버전 / Python 버전
- 실패 단계
- 터미널 로그
- 스크린샷
- server.log
```

## 참고 문서

- `docs/MACOS_SUPPORT_PLAN.md`
- `docs/MACOS_SMOKE_TEST_CHECKLIST.md`
- `docs/MACOS_SMOKE_TEST_RESULTS_TEMPLATE.md`
