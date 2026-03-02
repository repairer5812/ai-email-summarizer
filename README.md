# webmail-summary

메일을 자동으로 모으고, 읽기 쉽게 요약해주는 Windows용 로컬 앱입니다.

- 다운로드: https://github.com/repairer5812/ai-email-summarizer/releases/latest
- 프로젝트: https://github.com/repairer5812/ai-email-summarizer
- 현재 버전: `0.5.0`

## 일반 사용자용 안내 (먼저 읽어주세요)

컴퓨터를 잘 몰라도 아래 순서대로 하면 사용할 수 있습니다.

### 1. 설치하기

1) 위 `다운로드` 링크를 클릭합니다.
2) 최신 버전 파일을 내려받습니다.
3) 파일을 실행합니다.
4) 앱이 켜지면 브라우저 화면이 자동으로 열립니다.

### 2. 처음 설정하기

열린 화면에서 `/setup`을 열고 아래만 따라 하세요.

1) 메일 서버(IMAP) 정보 입력
2) `연결 테스트` 버튼 클릭
3) 가져올 메일 폴더 선택
4) AI 설정(로컬 또는 클라우드)
5) 저장 후 대시보드로 이동

### 3. 실제 사용하기

1) 대시보드에서 `동기화 시작` 클릭
2) 메일 수집/요약이 끝날 때까지 잠시 기다리기
3) 날짜별 카드에서 요약 확인
4) 필요하면 Obsidian 내보내기 사용

### 4. 업데이트하기

- 대시보드 우측 상단 버전 영역에서 `확인` 버튼을 누르면 최신 버전을 확인합니다.
- 새 버전이 있으면 `업데이트` 버튼으로 다운로드 페이지로 이동합니다.
- 당장 업데이트가 어렵다면 `1주일 안 보기` 또는 `이 버전 건너뛰기`를 사용할 수 있습니다.

### 5. 자주 겪는 문제

앱이 실행되지 않아요.
- 앱을 완전히 종료한 뒤 다시 실행해 보세요.

요약이 실패해요.
- 인터넷 연결을 확인하고 잠시 후 다시 시도해 보세요.

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

- 태그 푸시: `vX.Y.Z`
- GitHub Actions가 Windows 실행 파일/zip/SHA256 생성
- 체크리스트: `docs/RELEASE_CHECKLIST.md`

### 문서

- 변경 이력: `CHANGELOG.md`
- 보안 정책: `SECURITY.md`
- 기여 가이드: `CONTRIBUTING.md`
