# webmail-summary

IMAP 메일함을 자동으로 모으고, 읽기 쉽게 요약해주는 Windows용 로컬 앱입니다.

Daouoffice 전용이 아니라, IMAP을 제공하는 메일 서비스라면 대부분 사용할 수 있습니다.
(예: Gmail/Google Workspace, Outlook/Exchange(조직 정책상 IMAP 허용 시), 네이버/다음, 개인 도메인 메일 등)

- 다운로드: https://github.com/repairer5812/ai-email-summarizer/releases/latest
- 프로젝트: https://github.com/repairer5812/ai-email-summarizer
- 현재 버전: `0.5.55`

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

## 코드 서명 (SignPath Foundation)

Windows는 서명되지 않은 설치 파일에 대해 "Windows PC 보호"(SmartScreen) 경고를 표시할 수 있습니다.
이 프로젝트는 오픈소스 전환 후 SignPath Foundation을 통해 릴리즈 산출물을 코드 서명하는 흐름을 추가했습니다.

- 설정 문서: `docs/SIGNPATH_FOUNDATION.md`

## Code signing policy

Free code signing provided by SignPath.io, certificate by SignPath Foundation

- 정책 문서: `CODE_SIGNING_POLICY.md`
- 개인정보 처리/전송: `PRIVACY.md`

### 2. 처음 설정하기

브라우저로 열린 화면에서 상단의 `설정(Setup)` 메뉴를 누르고 아래만 따라 하세요.

참고: 주소창에 열린 주소가 `http://127.0.0.1:xxxxx/` 형태라면, 설정 화면은 `http://127.0.0.1:xxxxx/setup` 입니다.

1) 메일 서버(IMAP) 정보 입력
2) `연결 테스트` 버튼 클릭
3) 가져올 메일 폴더 선택 (원하는 폴더만 선택해서 동기화 가능)
4) AI 설정(로컬 또는 클라우드)
   - 로컬 기본값은 `빠름 — EXAONE 3.5 2.4B`이며, 필요 시 `표준(Gemma 3 4B)/성능`으로 변경할 수 있습니다.
5) 저장 후 대시보드로 이동

### 3. 실제 사용하기

1) 대시보드에서 `동기화 시작` 클릭
2) 메일 수집/요약이 끝날 때까지 잠시 기다리기
3) 날짜별 카드에서 요약 확인
4) 필요하면 Obsidian 내보내기 사용

### 4. 업데이트하기

- 대시보드 우측 상단 버전 영역에서 `확인` 버튼으로 최신 버전을 확인합니다.
- 자동 업데이트 적용은 Windows 설치형(`setup`) 파일 기준으로 동작합니다.
  - 포터블 `webmail-summary.exe`는 자동 설치 대상으로 사용되지 않습니다.
- 업데이트 채널/자동 확인/다운로드 URL/잠시 숨김/건너뛰기 설정은 `설정 > Advanced`에서 관리할 수 있습니다.

### 5. 자주 겪는 문제

앱이 실행되지 않아요.
- 앱을 완전히 종료한 뒤 다시 실행해 보세요.
- 로그 확인: `%LOCALAPPDATA%\webmail-summary\logs\server.log`
- 런타임 폴더: `%LOCALAPPDATA%\webmail-summary\runtime`

요약이 실패해요.
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
