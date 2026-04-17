# macOS 설치 및 실행 가이드

## 준비물

- **macOS** 12 (Monterey) 이상
- **Python 3.10+** (터미널에서 `python3 --version`으로 확인)
- 테스트용 IMAP 메일 계정 (Gmail, Daouoffice 등)

> Python이 없으면: `xcode-select --install` 실행 후 재확인, 또는 [python.org](https://www.python.org/downloads/macos/) 에서 설치

## 1. 소스 다운로드

```bash
# 방법 A: git clone
git clone https://github.com/repairer5812/ai-email-summarizer.git
cd ai-email-summarizer

# 방법 B: zip 다운로드
# https://github.com/repairer5812/ai-email-summarizer/releases/latest
# → Source code (zip) 다운로드 후 압축 해제
```

## 2. 환경 설정 및 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
python -m webmail_summary serve
```

브라우저가 자동으로 열립니다. 열리지 않으면 터미널에 표시된 `http://127.0.0.1:<port>/` 주소를 직접 열어주세요.

## 3. 초기 설정 (Setup)

앱이 열리면 설정 마법사가 나타납니다.

1. **IMAP 설정** — 메일 서버 주소, 계정 입력 후 "테스트" 클릭
2. **AI 설정** — 로컬 모델 또는 클라우드 API 선택
3. **Obsidian 설정** (선택) — 요약 노트를 저장할 폴더 지정

### AI 모델 선택

| 그룹 | 모델 | 특징 |
|------|------|------|
| **추천** | 빠름 — EXAONE 3.5 2.4B | 한국어 특화, 검증된 요약 품질 |
| **추천** | 초경량 — EXAONE 4.0 1.2B | 매우 빠름, 간단한 메일에 적합 |
| **추천** | 표준 — Gemma 4 E4B | 추론·코딩 대폭 향상 |
| **추천** | 성능 — Qwen 3.5 4B | 다국어·코딩 우수 |
| 기존 | Gemma 3 4B | 안정적 균형 품질 |
| 기존 | Qwen 2.5 3B | 짧은 메일 빠른 처리 |

- **Apple Silicon (M1/M2/M3/M4)**: 로컬 모델 권장. 설정에서 **추론 엔진을 MLX**로 선택하면 llama.cpp 대비 20~87% 더 빠른 추론이 가능합니다.
  - MLX 모델 (Apple Silicon 전용): EXAONE 4.0 1.2B, Gemma 4 E4B, Qwen 3.5 4B의 MLX 최적화 버전을 별도 제공합니다.
  - 설정 > AI > 추론 엔진에서 "자동" 선택 시, Apple Silicon이면 MLX를 자동으로 사용합니다.
- **Intel Mac**: 로컬 모델도 가능하나, 속도가 느릴 수 있습니다. 클라우드 API 권장.

## 4. 사용하기

1. 홈 화면에서 **동기화** 버튼 클릭
2. 메일 백업 → AI 요약 → Obsidian 내보내기 순서로 자동 진행
3. 날짜별 카드를 클릭하면 상세 요약 확인 가능

## 5. 재실행

```bash
cd ai-email-summarizer
source .venv/bin/activate
python -m webmail_summary serve
```

## 6. 업데이트

```bash
cd ai-email-summarizer
git pull
source .venv/bin/activate
pip install -e .
python -m webmail_summary serve
```

## 알려진 주의사항

| 증상 | 해결 |
|------|------|
| Keychain 접근 팝업 반복 | "항상 허용" 선택 |
| llama.cpp 실행 시 Gatekeeper 차단 | 시스템 설정 > 개인 정보 보호 > "확인 없이 열기" |
| 포트 충돌 (`Address already in use`) | `lsof -i :<port>` 로 확인 후 기존 프로세스 종료 |
| `pip install -e .` 실패 | `pip install --upgrade setuptools wheel` 후 재시도 |

## 데이터 저장 위치

```
~/Library/Application Support/WebmailSummary/
├── db.sqlite3          # 메일 메타데이터 + 설정
├── models/gguf/        # 다운로드된 GGUF 모델 파일
└── engines/llama.cpp/  # llama.cpp 바이너리

~/.cache/huggingface/hub/       # MLX 모델 캐시 (Apple Silicon 전용)
```

## 문의

- 이슈: https://github.com/repairer5812/ai-email-summarizer/issues
- 상세 테스트 가이드: `docs/MACOS_TEST_HANDOFF_KO.md`
