# webmail-summary

Local-first email archive and summarization app for Windows.

- Download: https://github.com/repairer5812/ai-email-summarizer/releases/latest
- Project: https://github.com/repairer5812/ai-email-summarizer
- Current version: `0.5.0`

## 한국어

`webmail-summary`는 다우오피스 IMAP 메일을 로컬에 아카이빙하고, 요약/태그/주제로 정리해 웹 UI로 보여주는 Windows 앱입니다.

### 주요 기능

- IMAP 메일 수집(폴더 선택)
- 원본 보존(raw `.eml`, 첨부, HTML/텍스트)
- HTML의 `cid:` 인라인 이미지 치환
- 외부 리소스(이미지/영상/CSS) 로컬 다운로드 후 링크 재작성
- 성공 처리 후에만 `\\Seen` 처리
- Obsidian용 Markdown 항상 생성(메일별/Daily/Topic)
- 업데이트 확인(최신 버전 체크, 1주일 숨김, 버전 건너뛰기)

### 설치(일반 사용자)

1. `releases/latest`에서 최신 Windows 배포 파일을 다운로드합니다.
2. 파일을 실행합니다(경고가 나오면 게시자/파일 출처를 확인하세요).
3. 앱 실행 후 `/setup`에서 IMAP 연결 테스트를 완료합니다.
4. 폴더와 AI 설정을 저장한 뒤 동기화를 시작합니다.

### 업데이트

- 대시보드 우측 상단의 버전 위젯에서 `확인`으로 최신 버전을 조회합니다.
- 새 버전이 있으면 `업데이트` 버튼으로 GitHub Releases 다운로드 페이지로 이동합니다.
- 알림은 `1주일 안 보기` 또는 `이 버전 건너뛰기`를 선택할 수 있습니다.

### 보안/개인정보

- API 키는 SQLite가 아니라 Windows Credential Manager(keyring)에 저장합니다.
- 메일 원본과 인덱스는 로컬 디스크에 저장됩니다.
- 클라우드 LLM 사용 시에만 요약 요청이 외부 API로 전송됩니다.

### 문제 해결

- 앱이 실행되지 않으면 먼저 재실행 후 `/setup` 연결 테스트를 다시 진행하세요.
- 네트워크 문제로 요약 실패 시(예: DNS 오류) 잠시 후 다시 시도하세요.
- 이슈 제보: https://github.com/repairer5812/ai-email-summarizer/issues

### 개발자 실행

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -U pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt
& ".\.venv\Scripts\pip.exe" install -e .
& ".\.venv\Scripts\webmail-summary.exe" serve
```

## English

`webmail-summary` is a Windows local-first app that archives IMAP emails and presents summaries, tags, and topics in a localhost web UI.

### What It Does

- Fetches IMAP emails from selected folders
- Preserves raw `.eml`, attachments, and HTML/plain bodies
- Rewrites `cid:` inline images and external assets to local paths
- Marks `\\Seen` only after successful local processing
- Always exports Obsidian-friendly Markdown (email/daily/topic)
- Supports update checks with snooze/skip controls

### Install (End Users)

1. Download the latest Windows package from:
   - https://github.com/repairer5812/ai-email-summarizer/releases/latest
2. Run the installer/package.
3. Open `/setup`, complete IMAP test and AI setup.
4. Start sync from the dashboard.

### Update Flow

- Use the top-right version widget on dashboard to check updates.
- Click `업데이트` to open the latest GitHub release download.

### Security Notes

- API keys are stored in Windows Credential Manager, not SQLite.
- Email archive/index stays local on your machine.

## Documents

- Changelog: `CHANGELOG.md`
- Security policy: `SECURITY.md`
- Contributing guide: `CONTRIBUTING.md`
