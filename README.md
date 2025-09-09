# 🤖 AI-Powered Email Summarizer

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Playwright](https://img.shields.io/badge/Playwright-1.40+-green.svg)](https://playwright.dev)
[![Gemini AI](https://img.shields.io/badge/Gemini-AI-orange.svg)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Dauoffice 웹메일에서 메일을 자동으로 수집하고, **Gemini AI**를 활용해 분류 및 요약하는 지능형 자동화 프로그램입니다.

## 🌟 포트폴리오 하이라이트

- **AI 통합**: Gemini AI를 활용한 스마트 메일 분류 및 요약
- **웹 자동화**: Playwright 기반 고급 웹 스크래핑
- **GUI 애플리케이션**: CustomTkinter로 구현한 사용자 친화적 인터페이스
- **보안 강화**: 암호화된 설정 파일 관리
- **자동화**: 스케줄링을 통한 완전 자동화
- **확장성**: 모듈화된 아키텍처로 쉬운 확장

## ✨ 주요 기능

### 📧 자동 메일 수집
- Dauoffice 웹메일에 자동 로그인
- 지정한 메일함에서 메일 수집
- 중복 메일 처리 방지
- 브라우저 실행 과정 관찰 모드 지원 (디버깅용)

### 🤖 AI 기반 메일 분류 및 요약
- **Gemini AI**를 활용한 스마트 분류
  - 카테고리: 경제뉴스, 에듀테크, AI, 행사, 개인적인 연락, 기타
  - 2-3문장으로 핵심 내용 요약
  - 중요도 판단 (High/Medium/Low)
  - 액션 필요 여부 판단
- **자동 출처 및 URL 추출**
  - 메일 내용에서 URL 자동 감지
  - 출처 정보 자동 추출 (출처:, source:, from: 등)
  - 뉴스 사이트 도메인 자동 인식

### 💾 유연한 결과 저장
- **Markdown (.md)**: Obsidian 등 노트앱 지원
- **텍스트 (.txt)**: 일반 텍스트 파일
- 원하는 폴더에 자유롭게 저장

### ⏰ 자동 스케줄링
- 매일 원하는 시간에 자동 실행
- 백그라운드에서 안전하게 동작

## 🚀 설치 및 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. Playwright 브라우저 설치
#### Windows
```bash
install_playwright.bat
```

#### Linux/Mac
```bash
chmod +x install_playwright.sh
./install_playwright.sh
```

또는 수동으로:
```bash
python -m playwright install
```

### 3. 프로그램 실행
```bash
python main.py
```

## ⚙️ 설정 방법

### 1. 설정 파일 생성
`config.example.json`을 `config.json`으로 복사하고 실제 정보를 입력하세요:

```bash
cp config.example.json config.json
```

### 2. Dauoffice 계정 설정
```json
{
  "dauoffice": {
    "username": "your_email@example.com",
    "password": "your_password",
    "target_folder": "받은편지함"
  }
}
```

### 3. AI API 설정
#### Gemini API (권장)
1. [Google AI Studio](https://aistudio.google.com/)에서 API Key 발급
2. `config.json`에 API Key 입력:
```json
{
  "gemini": {
    "api_key": "your_gemini_api_key_here"
  }
}
```

#### OpenAI API (선택사항)
1. [OpenAI Platform](https://platform.openai.com/)에서 API Key 발급
2. `config.json`에 API Key 입력:
```json
{
  "openai": {
    "api_key": "your_openai_api_key_here"
  }
}
```

### 4. 결과 저장 설정
```json
{
  "output": {
    "path": "./output",
    "file_format": ".md"
  }
}
```

### 5. 자동 실행 설정 (선택사항)
```json
{
  "schedule": {
    "enabled": 1,
    "time": "09:00"
  }
}
```

## 📋 실행 옵션

### 수동 실행
- **모든 메일 처리**: 중복 포함하여 모든 메일 처리
- **테스트 모드**: 최대 5개 메일만 처리 (테스트용)
- **실행과정 관찰하기**: 브라우저 창을 열어서 진행 상황 확인

## 🛠️ 기술 스택

### Backend
- **Python 3.8+** - 메인 프로그래밍 언어
- **Playwright** - 웹 자동화 및 스크래핑
- **Asyncio** - 비동기 프로그래밍

### AI & Machine Learning
- **Google Gemini AI** - 메일 분류 및 요약
- **OpenAI API** - 백업 AI 서비스

### Frontend
- **CustomTkinter** - 모던 GUI 프레임워크
- **Tkinter** - 기본 GUI 컴포넌트

### Security & Data
- **Cryptography** - 설정 파일 암호화
- **JSON** - 설정 및 데이터 관리
- **Pathlib** - 파일 시스템 관리

### Automation & Scheduling
- **Schedule** - 자동 실행 스케줄링
- **Threading** - 백그라운드 작업

## 📁 파일 구조

```
웹메일요약(webmail_summary)/
├── main.py                 # 메인 실행 파일
├── gui.py                  # GUI 인터페이스
├── mail_collector.py       # 메일 수집 엔진
├── ai_classifier.py        # AI 분류 및 요약
├── mail_summarizer.py      # 메일 요약 생성기
├── obsidian_manager.py     # Obsidian 연동 관리
├── file_manager.py         # 파일 관리 시스템
├── dynamic_category_manager.py # 동적 카테고리 관리
├── pagination_handler.py   # 페이지네이션 처리
├── security_manager.py     # 보안 관리
├── scheduler.py            # 자동 스케줄링
├── utils.py               # 유틸리티 함수
├── config.example.json    # 설정 예시 파일
├── requirements.txt       # 필요한 라이브러리
├── run.bat               # Windows 실행 스크립트
└── run.sh                # Linux/Mac 실행 스크립트
```

## 🔧 문제 해결

### 로그인 문제
- "실행과정 관찰하기" 체크박스를 선택하여 브라우저에서 직접 확인
- 아이디/비밀번호가 정확한지 확인
- 네트워크 연결 상태 확인

### AI 분류 문제
- Gemini API Key가 올바른지 확인
- API 사용량 초과 여부 확인
- 테스트 버튼으로 연결 상태 확인

### 파일 저장 문제
- 저장 폴더 경로가 존재하는지 확인
- 폴더 쓰기 권한 확인

## 📝 로그 확인

- `logs/` 폴더에 일별 실행 로그가 저장됩니다
- 오류 발생 시 로그를 확인하여 문제를 파악하세요

## 🔄 업데이트 이력

### 최신 버전 기능
- ✅ **Gemini AI** 통합 (OpenAI 대체)
- ✅ 브라우저 실행 과정 관찰 모드 추가
- ✅ 로그인 안정성 개선 (타임아웃 최적화)
- ✅ 설정 저장 로직 개선
- ✅ Obsidian/텍스트 파일 모두 지원
- ✅ URL 및 출처 자동 추출 기능
- ✅ 사용자 친화적 GUI 개선
- ✅ 동적 카테고리 관리 시스템
- ✅ 보안 강화 (암호화된 설정 저장)

## 🛡️ 보안 주의사항

- `config.json` 파일에는 민감한 정보가 포함되어 있습니다
- 이 파일을 Git에 커밋하지 마세요
- `.gitignore` 파일이 설정되어 있어 민감한 파일들이 자동으로 제외됩니다

## 🤝 지원

문제가 발생하거나 개선 사항이 있다면 이슈를 생성해 주세요.

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

**개발자**: Tekville  
**버전**: 2.0  
**최종 업데이트**: 2025년 1월
