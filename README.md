# webmail-summary

IMAP 메일함을 자동으로 모으고, 읽기 쉽게 요약해주는 Windows용 로컬 앱입니다.
macOS는 현재 설치형 배포 대신 **소스 기반 browser-mode 테스트**를 지원합니다.

Daouoffice 전용이 아니라, IMAP을 제공하는 메일 서비스라면 대부분 사용할 수 있습니다.
(예: Gmail/Google Workspace, Outlook/Exchange(조직 정책상 IMAP 허용 시), 네이버/다음, 개인 도메인 메일 등)

- 다운로드: https://github.com/repairer5812/ai-email-summarizer/releases/latest
- 프로젝트: https://github.com/repairer5812/ai-email-summarizer
- 최신 안정 버전: 위 `다운로드` 링크의 latest release 기준

## 일반 사용자용 안내 (먼저 읽어주세요)

컴퓨터를 잘 몰라도 아래 순서대로 하면 사용할 수 있습니다.

### 1. 설치하기

1) 위 `다운로드` 링크를 클릭합니다.
2) 최신 버전 파일을 내려받습니다.
   - 설치 파일(추천): `webmail-summary-setup-windows-x64-vX.Y.Z.exe`
   - 포터블(설치 없이 실행): `webmail-summary.exe`
   - 포터블 ZIP: `webmail-summary-windows-x64.zip`
3) 파일을 실행합니다.
4) 앱이 켜지면 창이 자동으로 열립니다.

### 1-1. 설치 중 Windows 보안 경고가 뜨면 (정상입니다)

이 앱은 아직 코드 서명 인증서가 없어서, 내려받거나 처음 실행할 때 Windows가 보안 경고를 띄울 수 있습니다. 바이러스라서가 아니라, "게시자가 아직 검증되지 않은 새 프로그램"이라서 뜨는 안내입니다. 아래대로 하시면 됩니다.

1) **브라우저 다운로드 경고가 뜨면**: 파일 이름 옆 점 세 개(⋯)나 경고 메시지에서 `유지`(Keep) 또는 `계속`을 선택해 다운로드를 마칩니다.
2) **파란색 경고 창("Windows의 PC를 보호했습니다")이 뜨면**: 가운데의 **`추가 정보`**(More info)를 클릭한 뒤, 아래에 나타나는 **`실행`**(Run anyway) 버튼을 누릅니다.
3) **"이 앱이 디바이스를 변경할 수 있도록 허용하시겠어요?"(사용자 계정 컨트롤) 창이 뜨면**: `예`를 누릅니다.

걱정되시면 같은 릴리즈에 함께 올라온 `SHA256SUMS.txt`로 내려받은 파일의 해시를 직접 대조하실 수 있습니다. 모든 실행 파일은 공개된 소스에서 GitHub Actions가 자동으로 빌드합니다.

### 1-2. macOS 테스트용 다운로드

- 현재는 **macOS 전용 설치 파일(`.dmg` / `.app`)이 없습니다.**
- macOS 테스트는 **Windows 실행 파일을 받는 것이 아니라, 소스 코드를 내려받아 browser-mode로 실행**해야 합니다.
- 가장 쉬운 방법:
  - 최신 릴리즈의 `Source code (zip)` 또는 `Source code (tar.gz)` 다운로드
  - 예: `https://github.com/repairer5812/ai-email-summarizer/archive/refs/tags/v0.6.6.14.zip`
  - 예: `https://github.com/repairer5812/ai-email-summarizer/archive/refs/tags/v0.6.6.14.tar.gz`
- 또는 git 사용 가능하면:

```bash
git clone https://github.com/repairer5812/ai-email-summarizer.git
```

- 실행 방법은 `docs/MACOS_TEST_HANDOFF_KO.md`를 따라 주세요.

## 코드 서명 및 Windows 경고

현재 이 앱의 실행 파일은 **코드 서명되어 있지 않습니다.** (무료 오픈소스 서명 프로그램인 SignPath Foundation에 신청했으나 승인되지 않았습니다.) 그래서 설치·첫 실행 시 Windows SmartScreen 경고가 뜰 수 있으며, 이는 정상입니다. 넘어가는 방법은 위 **`1-1. 설치 중 Windows 보안 경고가 뜨면`** 을 참고하세요.

안전성은 다음으로 확인할 수 있습니다.

- 모든 산출물은 공개 소스에서 GitHub Actions가 자동으로 빌드합니다(수동 업로드가 아님).
- 각 릴리즈의 `SHA256SUMS.txt`로 내려받은 파일의 무결성을 직접 대조할 수 있습니다.
- 정책 문서: `CODE_SIGNING_POLICY.md`
- 개인정보 처리/전송: `PRIVACY.md`

### 2. 처음 설정하기

브라우저로 열린 화면에서 상단의 `설정(Setup)` 메뉴를 누르고 아래만 따라 하세요.

참고: 주소창에 열린 주소가 `http://127.0.0.1:xxxxx/` 형태라면, 설정 화면은 `http://127.0.0.1:xxxxx/setup` 입니다.

1) 메일 서버(IMAP) 정보 입력
2) `연결 테스트` 버튼 클릭
3) 가져올 메일 폴더 선택 (원하는 폴더만 선택해서 동기화 가능)
4) AI 설정(로컬 또는 클라우드)
   - 로컬 기본값은 `빠름 — EXAONE 3.5 2.4B`이며, 필요 시 `표준(Gemma 4 E4B)/성능(Qwen 3.5 4B)`으로 변경할 수 있습니다.
   - 설정 화면에서 설치된 모델의 용량 확인과 삭제가 가능합니다.
5) 저장 후 대시보드로 이동

### 3. 실제 사용하기

1) 대시보드에서 `동기화 시작` 클릭
2) 메일 수집/요약이 끝날 때까지 잠시 기다리기
3) 날짜별 카드에서 각 날짜의 요약과 `날짜별 개요(daily overview)` 확인
4) 필요하면 여러 날짜를 선택해서 `선택 날짜 오류만 다시 요약` 실행
   - `(no summary)`, `(LLM timeout)`, placeholder 요약처럼 실패한 항목만 다시 시도합니다.
   - 여러 날짜를 한 번에 골라 묶어서 처리할 수 있습니다.
5) 필요하면 특정 날짜 1개를 선택해서 `선택 날짜 전체 다시 요약` 실행
   - 해당 날짜의 모든 이메일을 다시 요약하고
   - 이어서 그 날짜의 `daily overview`도 다시 생성합니다.
6) 필요하면 Obsidian 내보내기 사용

### 3-1. 클라우드 멀티모달(이미지 함께 읽기)

- 클라우드 모델을 쓸 때는 `설정 > AI Configuration`에서 `클라우드 멀티모달`을 켤 수 있습니다.
- 이 기능은 Vision 지원 클라우드 모델에서만 동작합니다.
  - 예: GPT-4o, Gemini, Claude 계열 일부 모델
- 설정 화면에서 현재 선택한 모델이 Vision 지원인지 안내를 볼 수 있습니다.
- 이미지가 많아도 작은 로고/아이콘/작은 배너는 자동으로 제외하고,
  핵심 이미지 위주로만 함께 보냅니다.

### 4. 업데이트하기

- **새 버전이 나오면 앱을 켤 때 자동으로 알림 모달이 뜹니다.** 별도로 `확인` 버튼을 누를 필요가 없습니다.
  - 앱 시작 시 백그라운드에서 GitHub 릴리스를 1회 조회합니다.
  - 새 버전이 있으면 홈 화면 진입 시 모달이 자동 표시됩니다.
  - 같은 버전에 대해 `나중에`를 누르면 같은 세션 동안 다시 안 뜹니다.
  - 24시간/1주일 미루기 또는 이 버전 영구 건너뛰기 옵션도 모달 안에 있습니다.
- 수동 확인은 대시보드 우측 상단 버전 영역의 `확인` 버튼으로 언제든 가능합니다.
- 자동 업데이트 적용은 Windows 설치형(`setup`) 파일 기준으로 동작합니다.
  - 포터블 `webmail-summary.exe`는 자동 설치 대상으로 사용되지 않습니다.
- 보안: 다운로드 후 SHA256 체크섬으로 무결성을 검증합니다. 체크섬이 없으면 설치를 중단합니다.
- 업데이트 채널/자동 확인 끄기/다운로드 URL/잠시 숨김/건너뛰기 설정은 `설정 > Advanced`에서 관리할 수 있습니다.

### 5. 자주 겪는 문제

앱이 실행되지 않아요.
- 앱을 완전히 종료한 뒤 다시 실행해 보세요.
- 로그 확인: `%LOCALAPPDATA%\webmail-summary\logs\server.log`
- 런타임 폴더: `%LOCALAPPDATA%\webmail-summary\runtime`
- 앱 창 대신 브라우저로 열렸거나 시작 오류가 반복되면 `%LOCALAPPDATA%\webmail-summary\reports` 아래의 로컬 오류 리포트도 함께 확인해 보세요.

요약이 실패해요.
- **자동으로 다음 동기화 때 재시도됩니다.** `(LLM timeout)`·`(LLM 응답 timeout)` 같이 표시된 메일은 읽음으로 처리되지 않으며, 다음 sync에서 자동으로 다시 LLM을 부릅니다.
- 즉시 다시 시도하려면 대시보드에서 여러 날짜를 선택한 뒤 `선택 날짜 오류만 다시 요약`을 누르세요. 실패한 요약만 모아서 다시 돌립니다.
- 인터넷 연결을 확인하고 잠시 후 다시 시도해 보세요.

Daouoffice가 아닌 메일도 되나요?
- 네. 이 앱은 IMAP 기반이라 IMAP이 열려 있는 메일 서비스면 대부분 동작합니다.
- 다만 조직/학교 메일은 정책상 IMAP이 꺼져 있을 수 있습니다.
- Gmail/Google Workspace는 2단계 인증 사용 시 앱 비밀번호가 필요할 수 있습니다.

비밀번호/API 키가 걱정돼요.
- 키는 DB가 아니라 Windows Credential Manager에 저장됩니다.

문제가 계속되면 여기에 알려주세요:
https://github.com/repairer5812/ai-email-summarizer/issues

## 이 앱이 하는 일

- IMAP 메일 수집 (폴더 선택 가능)
- 메일 원본 보존 (`.eml`, 첨부, HTML/텍스트)
- 외부 리소스를 로컬에 저장하고 링크 재작성
- 개별 이메일 요약 생성
- 실패한 요약만 선택 재시도 / 특정 날짜 전체 재요약
- 날짜별 개요(`daily overview`) 자동 생성 및 갱신
- 성공 처리 후에만 `\Seen` 처리
- Obsidian용 Markdown 생성 (메일별, Daily, Topic)

## 개발자용 안내

아래는 코드를 수정하거나 개발할 때만 필요합니다.

### 로컬 개발 실행

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -U pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt
& ".\.venv\Scripts\pip.exe" install -e .
& ".\.venv\Scripts\webmail-summary.exe" serve
```

### 릴리즈

- `pyproject.toml`의 버전과 `CHANGELOG.md`를 먼저 갱신합니다.
- 태그 푸시: `vX.Y.Z` (태그 푸시가 있어야 GitHub Release 워크플로가 실행됩니다)
- 체크리스트: `docs/RELEASE_CHECKLIST.md`

### 랜딩페이지 (Next.js)

- 위치: `landing/`
- 실행:

```bash
cd landing
npm install
npm run dev
```

- Vercel 배포 시 Root Directory를 `landing`으로 설정합니다.

### 문서

- 변경 이력: `CHANGELOG.md`
- 보안 정책: `SECURITY.md`
- 기여 가이드: `CONTRIBUTING.md`
