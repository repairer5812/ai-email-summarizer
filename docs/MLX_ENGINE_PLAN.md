# MLX Engine Integration Plan

**Branch:** `feat/mlx-engine`
**Author:** Claude + ckc3705
**Created:** 2026-04-17
**Status:** Implemented (Phase 0~5 complete)

---

## Goal

macOS Apple Silicon (M1+) 환경에서 llama.cpp 대신 MLX 프레임워크를 사용하여
로컬 LLM 추론 속도를 20~87% 향상시키는 엔진을 추가한다.
기존 llama.cpp 엔진은 그대로 유지하며, macOS + Apple Silicon에서만 MLX를 선택할 수 있도록 한다.

---

## Architecture Overview

```
현재:
  Settings → provider.py → LlamaCppServerProvider → llama-server (port 4891) → /v1/chat/completions

추가:
  Settings → provider.py → MLXServerProvider → mlx_lm.server (port 4892) → /v1/chat/completions
                         ↘ (fallback) LlamaCppServerProvider
```

핵심: `mlx_lm.server`가 llama-server와 동일한 OpenAI-compatible API를 제공하므로,
기존 `LlamaCppServerProvider`의 HTTP 호출 패턴을 거의 그대로 재사용할 수 있다.

---

## MLX Model Availability (mlx-community on HuggingFace)

| 현재 GGUF 모델 | MLX 대응 모델 | HF Repo |
|----------------|--------------|---------|
| EXAONE 3.5 2.4B (Q4_K_M) | EXAONE 3.5 2.4B 4bit | mlx-community/EXAONE-3.5-2.4B-Instruct-4bit (확인 필요) |
| Gemma 4 E4B (Q4_K_M) | Gemma 4 E4B 4bit | mlx-community/gemma-4-E4B-it-4bit (확인 필요) |
| Qwen 3.5 4B (Q4_K_M) | Qwen 3.5 4B 4bit | mlx-community/Qwen3.5-4B-MLX-4bit |
| Gemma 3 4B (Q4_K_M) | Gemma 3 4B 4bit | mlx-community/gemma-3-4b-it-4bit |
| Qwen 2.5 3B (Q4_K_M) | (확인 필요) | - |

---

## Task Breakdown

### Phase 0: 사전 준비
- [ ] **0-1** 플랫폼 감지 유틸리티 작성
  - 파일: `src/webmail_summary/util/platform_caps.py`
  - `is_apple_silicon() -> bool` — macOS + arm64 감지
  - `is_mlx_available() -> bool` — mlx 패키지 import 가능 여부
  - 테스트: `tests/test_platform_caps.py`

- [ ] **0-2** MLX 모델 레지스트리 추가
  - 파일: `src/webmail_summary/llm/local_models.py`
  - `LocalModelChoice`에 `engine` 필드 추가 (`"gguf"` | `"mlx"`)
  - MLX 모델 3종 추가 (EXAONE 3.5, Gemma 4 E4B, Qwen 3.5 4B)
  - group: `"mlx"` 별도 그룹
  - 기존 GGUF 모델의 `engine` 기본값 `"gguf"`

- [ ] **0-3** Settings에 `local_engine` 필드 추가
  - 파일: `src/webmail_summary/index/settings.py`
  - 새 필드: `local_engine: str` (`"auto"` | `"llamacpp"` | `"mlx"`)
  - `"auto"`: Apple Silicon이면 MLX, 아니면 llama.cpp
  - DB key: `"local_engine"`

### Phase 1: MLX 엔진 설치
- [ ] **1-1** MLX 런타임 설치 관리자
  - 파일: `src/webmail_summary/llm/mlx_engine.py`
  - `ensure_mlx_installed() -> bool`
    - `pip install mlx-lm` (venv 또는 시스템)
    - 또는 `uvx`로 격리 실행 지원
  - `find_mlx_server_command() -> list[str]`
    - `["python", "-m", "mlx_lm.server"]` 또는 `["uvx", "--from", "mlx-lm", "mlx_lm.server"]`
  - Apple Silicon이 아닌 환경에서는 즉시 `False` 반환

- [ ] **1-2** MLX 모델 다운로드 로직
  - 파일: `src/webmail_summary/llm/mlx_download.py`
  - MLX 모델은 GGUF와 달리 **여러 파일** (config.json, tokenizer.json, model.safetensors 등)
  - 방법 A: `huggingface_hub.snapshot_download()` 활용 (의존성 추가)
  - 방법 B: `mlx_lm.server`가 자동 다운로드 지원 (모델명만 전달하면 자동 캐시)
  - **방법 B 채택** — mlx_lm.server에 `--model <hf_repo>` 전달 시 자동 다운로드
  - 저장 경로: HuggingFace 기본 캐시 (`~/.cache/huggingface/`)
  - `.complete` 마커: 첫 서버 시작 성공 시 생성

- [ ] **1-3** MLX 모델 상태 확인
  - 파일: `src/webmail_summary/llm/mlx_status.py`
  - `check_mlx_ready(model_id: str) -> MlxReady`
    - `mlx_available`: MLX 패키지 설치 여부
    - `apple_silicon`: Apple Silicon 여부
    - `model_cached`: HF 캐시에 모델 존재 여부
  - UI에서 상태 표시용

### Phase 2: MLX 서버 프로바이더
- [ ] **2-1** MLXServerProvider 구현
  - 파일: `src/webmail_summary/llm/mlx_server.py`
  - `LlamaCppServerProvider`와 동일한 패턴:
    - `mlx_lm.server` 프로세스 spawning (port 4892)
    - `--model <hf_repo_id>` 인자로 모델 지정
    - Health check: `GET /v1/models`
    - Inference: `POST /v1/chat/completions` (동일 포맷)
    - Idle timeout: 600s
    - 프로세스 관리 (start/stop/restart)
  - 차이점:
    - 포트: 4892 (llama-server 4891과 충돌 방지)
    - 서버 명령: `python -m mlx_lm.server --model <repo> --port 4892`
    - 모델 로드 시간이 다를 수 있음 (health check 타임아웃 조정)

- [ ] **2-2** Provider 팩토리 수정
  - 파일: `src/webmail_summary/llm/provider.py`
  - `get_llm_provider()` 분기 추가:
    ```
    if backend == "local":
        engine = resolve_engine(settings)  # "mlx" or "llamacpp"
        if engine == "mlx":
            return MLXServerProvider(...)
        else:
            return LlamaCppServerProvider(...)  # 기존 로직
    ```
  - `resolve_engine(settings) -> str`:
    - `settings.local_engine == "mlx"` → `"mlx"`
    - `settings.local_engine == "llamacpp"` → `"llamacpp"`
    - `settings.local_engine == "auto"` → Apple Silicon이면 `"mlx"`, 아니면 `"llamacpp"`

- [ ] **2-3** 프롬프트 호환성 확인
  - `LlamaCppServerProvider`의 프롬프트 템플릿 재사용
  - MLX 모델별 chat_template이 다를 수 있으므로 검증 필요
  - `mlx_lm.server`가 chat_template을 자동 적용하므로 큰 문제 없을 것으로 예상

### Phase 3: UI 통합
- [ ] **3-1** Setup 페이지: 엔진 선택 드롭다운
  - 파일: `src/webmail_summary/ui/templates/setup.html`
  - 로컬 설정 영역에 "엔진 선택" 추가:
    - 자동 (Apple Silicon이면 MLX, 아니면 llama.cpp)
    - llama.cpp (모든 플랫폼)
    - MLX (Apple Silicon 전용)
  - Apple Silicon이 아닌 경우 MLX 옵션 disabled + 안내 메시지

- [ ] **3-2** Setup 페이지: 모델 드롭다운 연동
  - 엔진 변경 시 모델 목록 필터링 (JS)
  - MLX 선택 → MLX 모델만 표시
  - llama.cpp 선택 → GGUF 모델만 표시
  - 자동 선택 → 전체 표시 (적합한 모델 자동 매칭)

- [ ] **3-3** Setup 라우트: 엔진 설정 저장
  - 파일: `src/webmail_summary/ui/routes_setup.py`
  - `local_engine` 필드 저장 로직 추가
  - 엔진 변경 시 기존 서버 프로세스 종료 로직

- [ ] **3-4** 설치 버튼: MLX 엔진 + 모델 설치
  - 파일: `src/webmail_summary/jobs/tasks_local_install.py`
  - MLX 모델 설치 태스크 분기:
    - GGUF: 기존 다운로드 로직
    - MLX: `mlx_lm.server` 첫 실행으로 자동 다운로드 (또는 snapshot_download)
  - 진행률 표시 (MLX 모델은 여러 파일이라 진행률 계산 방식 다름)

- [ ] **3-5** Home 페이지: 현재 엔진 표시
  - AI 상태 영역에 "(MLX)" 또는 "(llama.cpp)" 표시
  - 추론 속도 차이를 사용자가 인지할 수 있도록

### Phase 4: 안정화 & 폴백
- [ ] **4-1** MLX → llama.cpp 자동 폴백
  - MLX 서버 시작 실패 시 llama.cpp로 자동 전환
  - 사용자에게 알림 (로그 + UI 메시지)

- [ ] **4-2** 모델 호환성 매핑
  - MLX 모델과 GGUF 모델 간 1:1 매핑 테이블
  - 엔진 변경 시 대응 모델 자동 전환
  - 예: `gemma4_e4b` (GGUF) ↔ `mlx_gemma4_e4b` (MLX)

- [ ] **4-3** 타임아웃 & 리소스 튜닝
  - MLX 모델별 적정 타임아웃 측정
  - 메모리 사용량 모니터링 (통합 메모리 특성 고려)
  - idle shutdown 타이머 조정

- [ ] **4-4** 에러 핸들링 강화
  - MLX 미설치 → 안내 메시지
  - Apple Silicon이 아닌 Mac → llama.cpp 권장 안내
  - 모델 다운로드 실패 → 재시도 + GGUF 폴백 안내

### Phase 5: 테스트 & 문서
- [ ] **5-1** 단위 테스트
  - `tests/test_platform_caps.py` — 플랫폼 감지 목(mock) 테스트
  - `tests/test_mlx_provider.py` — MLXServerProvider 목 테스트
  - `tests/test_provider_factory.py` — 엔진 분기 로직 테스트

- [ ] **5-2** 통합 테스트 (macOS 실기기)
  - Apple Silicon Mac에서 실제 MLX 서버 시작 → 추론 → 결과 검증
  - llama.cpp 대비 속도 비교 측정
  - 폴백 시나리오 검증

- [ ] **5-3** 문서 업데이트
  - `docs/MACOS_INSTALL_GUIDE_KO.md` — MLX 엔진 안내 추가
  - `CHANGELOG.md` — MLX 지원 기록
  - `AGENTS.md` — MLX 관련 아키텍처 설명 추가

---

## File Change Summary

| 파일 | 변경 유형 | Phase |
|------|----------|-------|
| `src/webmail_summary/util/platform_caps.py` | **신규** | 0-1 |
| `tests/test_platform_caps.py` | **신규** | 0-1 |
| `src/webmail_summary/llm/local_models.py` | 수정 | 0-2 |
| `src/webmail_summary/index/settings.py` | 수정 | 0-3 |
| `src/webmail_summary/llm/mlx_engine.py` | **신규** | 1-1 |
| `src/webmail_summary/llm/mlx_download.py` | **신규** | 1-2 |
| `src/webmail_summary/llm/mlx_status.py` | **신규** | 1-3 |
| `src/webmail_summary/llm/mlx_server.py` | **신규** | 2-1 |
| `src/webmail_summary/llm/provider.py` | 수정 | 2-2 |
| `src/webmail_summary/ui/templates/setup.html` | 수정 | 3-1, 3-2 |
| `src/webmail_summary/ui/routes_setup.py` | 수정 | 3-3 |
| `src/webmail_summary/jobs/tasks_local_install.py` | 수정 | 3-4 |
| `src/webmail_summary/ui/templates/home.html` | 수정 | 3-5 |
| `tests/test_mlx_provider.py` | **신규** | 5-1 |
| `tests/test_provider_factory.py` | **신규** | 5-1 |
| `docs/MACOS_INSTALL_GUIDE_KO.md` | 수정 | 5-3 |

---

## Key Design Decisions

### 1. mlx_lm.server 사용 (자체 MLX 코드 작성 X)
- `mlx_lm.server`가 OpenAI-compatible API를 이미 제공
- llama-server와 동일한 `/v1/chat/completions` 엔드포인트
- 모델 자동 다운로드, chat_template 자동 적용
- 우리는 HTTP 클라이언트만 작성하면 됨 (LlamaCppServerProvider 재사용)

### 2. MLX를 Python 의존성에 추가하지 않음
- `mlx`, `mlx-lm`은 macOS 전용 → requirements.txt에 넣으면 Windows/Linux 설치 실패
- 대신 런타임에 `pip install mlx-lm` 또는 `uvx` 격리 실행
- 기존 llama.cpp 바이너리 다운로드 패턴과 유사한 접근

### 3. 포트 분리 (4891 vs 4892)
- llama-server: 4891 (기존)
- mlx_lm.server: 4892 (신규)
- 엔진 전환 시 충돌 방지

### 4. 모델 ID 분리
- GGUF 모델: `fast`, `gemma4_e4b`, `qwen35_4b` (기존 ID)
- MLX 모델: `mlx_fast`, `mlx_gemma4_e4b`, `mlx_qwen35_4b` (신규 ID)
- 엔진 변경 시 자동 매핑

---

## Risk & Mitigation

| 리스크 | 영향 | 대응 |
|--------|------|------|
| mlx-lm 설치 실패 | MLX 사용 불가 | llama.cpp 폴백 |
| MLX 모델 HF 캐시 용량 | 디스크 사용 증가 | 안내 메시지 + 수동 정리 가이드 |
| mlx_lm.server API 변경 | 호환성 깨짐 | 버전 고정 (`mlx-lm>=0.x.y`) |
| 메모리 부족 (8GB Mac) | OOM 크래시 | 모델 크기별 권장 RAM 표시 |
| Windows/Linux에서 MLX 선택 시도 | 에러 | UI에서 disabled + 안내 |

---

## Estimated Scope

- **신규 파일**: 7개
- **수정 파일**: 9개
- **예상 코드량**: ~1,500줄 (테스트 포함)
- Phase 0~2 (엔진 핵심): 우선 구현
- Phase 3~5 (UI/테스트/문서): 후속 구현
