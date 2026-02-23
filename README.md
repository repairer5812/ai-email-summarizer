# webmail-summary

## 한국어

Windows(10/11)에서 다우오피스 IMAP 메일을 로컬로 아카이빙하고, 요약/태그/주제로 정리해서 GUI로 보여주는 로컬 앱입니다.

- IMAP으로 메일 수집 (폴더 선택 가능)
- 원본 보존: raw `.eml` + 첨부 + HTML/텍스트
- HTML 내부의 `cid:` 인라인 이미지 치환
- HTML에 있는 외부 URL 이미지/영상/CSS 리소스도 다운로드 후 로컬 참조로 rewrite (기본 제한 1GB)
- 처리 성공 시에만 서버에 `\\Seen`(읽음) 처리
- Obsidian용 Markdown을 항상 생성 (메일별 + Daily + Topic, 태그/백링크 포함)
- GUI: FastAPI localhost(127.0.0.1) 웹 UI

### 빠른 시작(테스트)

프로젝트 루트에서 PowerShell 실행:

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -U pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt
& ".\.venv\Scripts\pip.exe" install -e .

& ".\.venv\Scripts\webmail-summary.exe" serve
```

브라우저가 열리면 `/setup`에서 IMAP 테스트 후 폴더를 선택하고 저장하세요.

또는 명령어를 치기 싫으면:
- `run_dev.cmd` 더블클릭

### AI 설정(OpenRouter)

이 앱은 AI 기능(요약/태그/주제)이 핵심입니다.

권장 흐름:
- Local AI 설치 (llama.cpp + HuggingFace GGUF 모델 다운로드)
- 필요하면 OpenRouter를 fallback으로 설정

OpenRouter 설정(옵션):
- Setup 화면에서 OpenRouter model(예: `openai/gpt-4o-mini`)과 API key를 입력
- API key는 SQLite에 저장하지 않고, Windows Credential Manager(keyring)에 저장합니다.

### 테스트 방법(상세)

`test.txt` 참고.

## English

Local-first Windows app that archives Daouoffice IMAP mail and presents summaries/tags/topics in a localhost GUI.

- IMAP fetch (select mailbox/folder)
- Preserve originals: raw `.eml` + attachments + HTML/plain text
- Rewrite `cid:` inline images
- Download external assets referenced by email HTML (images/video/CSS) and rewrite to local paths (default limit 1GB)
- Mark `\\Seen` only after archive + DB index + Obsidian export succeed
- Always generates Obsidian-friendly Markdown (per-email + daily + topic) with tags/backlinks
- GUI served by FastAPI on 127.0.0.1

### Quick start (for testing)

From repo root:

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -U pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt
& ".\.venv\Scripts\pip.exe" install -e .

& ".\.venv\Scripts\webmail-summary.exe" serve
```

### AI setup (OpenRouter)

AI summarization/tags/topics is the core feature.

Recommended:
- Install Local AI (llama.cpp + HuggingFace GGUF models)
- Optionally configure OpenRouter as a fallback

OpenRouter (optional):
- Configure OpenRouter model (e.g. `openai/gpt-4o-mini`) and API key in Setup
- The API key is stored via Windows Credential Manager (keyring), not in SQLite
