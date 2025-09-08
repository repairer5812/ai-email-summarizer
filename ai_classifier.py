import json
import logging
import re
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from openai import OpenAI

logger = logging.getLogger(__name__)

class AIClassifier:
    def __init__(self, config_path="config.json", api_key=None, config_dict=None):
        """AI 분류기 초기화"""
        # 설정 딕셔너리가 직접 전달된 경우 (GUI에서 복호화된 설정 사용)
        if config_dict:
            self.config = config_dict
        # API 키가 직접 전달된 경우 (테스트 목적)
        elif api_key and len(api_key) > 20:  # API 키처럼 보이는 긴 문자열
            self.config = {
                "gemini": {"api_key": api_key},
                "openai": {"api_key": ""},
                "api": {"primary": "gemini", "fallback": "openai"}
            }
        else:
            # 일반적인 경우: config 파일 로드
            self.config = self._load_config(config_path)
        
        # API 설정
        self.primary_api = self.config.get('api', {}).get('primary', 'gemini')
        self.fallback_api = self.config.get('api', {}).get('fallback', 'openai')
        self.current_api = self.primary_api
        
        # API 클라이언트 초기화
        self._init_apis()
        
        # 기본 카테고리
        self.default_categories = [
            "경제뉴스", "기술동향", "업무지시", "공지사항", 
            "미팅일정", "보고서", "기타"
        ]
        
    def _load_config(self, config_path):
        """설정 파일 로드"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"설정 파일 로드 실패: {e}")
            return {}
    
    def _init_apis(self):
        """API 클라이언트 초기화"""
        # Gemini API 초기화
        gemini_key = self.config.get('gemini', {}).get('api_key')
        if gemini_key:
            try:
                genai.configure(api_key=gemini_key)
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            except Exception as e:
                logger.error(f"Gemini API 초기화 실패: {e}")
                self.gemini_model = None
        else:
            self.gemini_model = None
            
        # OpenAI API 초기화
        openai_key = self.config.get('openai', {}).get('api_key')
        if openai_key and openai_key != "YOUR_OPENAI_API_KEY_HERE":
            try:
                self.openai_client = OpenAI(api_key=openai_key)
            except Exception as e:
                logger.error(f"OpenAI API 초기화 실패: {e}")
                self.openai_client = None
        else:
            self.openai_client = None
        
    def test_connection(self, api_type=None):
        """API 연결 테스트"""
        if api_type is None:
            api_type = self.current_api
            
        if api_type == 'gemini' and self.gemini_model:
            try:
                response = self.gemini_model.generate_content("Hello, test")
                logger.info("Gemini API 연결 성공")
                return True
            except Exception as e:
                logger.error(f"Gemini API 테스트 실패: {e}")
                return False
                
        elif api_type == 'openai' and self.openai_client:
            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "Hello, test"}],
                    max_tokens=10
                )
                logger.info("OpenAI API 연결 성공")
                return True
            except Exception as e:
                logger.error(f"OpenAI API 테스트 실패: {e}")
                return False
                
        return False
    
    def classify_mail(self, mail_data):
        """메일 분류 및 요약"""
        # URL과 출처 추출
        urls, sources = self._extract_urls_and_sources(mail_data)
        
        # 현재 설정된 API로 분류 시도
        try:
            classification = self._classify_with_ai(mail_data, urls, sources)
            return classification
        except Exception as e:
            logger.warning(f"{self.current_api} API 실패, 대체 API로 시도: {e}")
            
            # 대체 API로 시도
            if self._switch_to_fallback():
                try:
                    classification = self._classify_with_ai(mail_data, urls, sources)
                    return classification
                except Exception as fallback_error:
                    logger.error(f"대체 API도 실패: {fallback_error}")
                    raise
            else:
                logger.error("사용 가능한 대체 API가 없습니다")
                raise
    
    def _switch_to_fallback(self):
        """대체 API로 전환"""
        if self.current_api == self.primary_api:
            if self.fallback_api == 'openai' and self.openai_client:
                self.current_api = 'openai'
                logger.info("OpenAI API로 전환")
                return True
            elif self.fallback_api == 'gemini' and self.gemini_model:
                self.current_api = 'gemini'
                logger.info("Gemini API로 전환")
                return True
        return False
    
    def _extract_urls_and_sources(self, mail_data):
        """메일 내용에서 URL과 출처 정보 추출"""
        content = f"{mail_data.get('subject', '')} {mail_data.get('content', '')}"
        
        # URL 추출 (http/https로 시작하는 URL)
        url_pattern = r'https?://[^\s<>"\'\[\]()]+'
        urls = re.findall(url_pattern, content, re.IGNORECASE)
        
        # 중복 제거 및 정리
        urls = list(set(urls))
        
        # 출처 정보 추출 (일반적인 출처 표현 패턴)
        sources = []
        
        # 패턴: "출처:", "source:", "from:", "참고:", "ref:" 등으로 시작하는 부분
        source_patterns = [
            r'출처[:\s]+([^\n\r]+)',
            r'[Ss]ource[:\s]+([^\n\r]+)',
            r'[Ff]rom[:\s]+([^\n\r]+)',
            r'참고[:\s]+([^\n\r]+)',
            r'[Rr]ef[:\s]+([^\n\r]+)',
            r'기사제공[:\s]+([^\n\r]+)',
            r'제공[:\s]+([^\n\r]+)'
        ]
        
        for pattern in source_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                source = match.strip()
                if source and len(source) < 100:  # 너무 긴 텍스트는 제외
                    sources.append(source)
        
        # 중복 제거
        sources = list(set(sources))
        
        # URL에서 도메인명 추출하여 출처로 사용
        for url in urls:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc
                if domain and domain not in sources:
                    # 일반적인 뉴스 사이트 도메인명 정리
                    if any(news_site in domain for news_site in ['news', 'times', 'post', 'herald']):
                        sources.append(domain)
            except:
                pass
        
        return urls[:5], sources[:3]  # 최대 5개 URL, 3개 출처만 반환
    
    def _classify_with_ai(self, mail_data, urls=None, sources=None):
        """AI를 사용한 분류 (현재 설정된 API 사용)"""
        if self.current_api == 'gemini':
            return self._classify_with_gemini(mail_data, urls, sources)
        elif self.current_api == 'openai':
            return self._classify_with_openai(mail_data, urls, sources)
        else:
            raise ValueError(f"지원하지 않는 API: {self.current_api}")
    
    def _classify_with_gemini(self, mail_data, urls=None, sources=None):
        """Gemini AI를 사용한 분류"""
        if not self.gemini_model:
            raise Exception("Gemini API가 초기화되지 않았습니다")
            
        prompt = self._create_classification_prompt(mail_data, urls, sources)
        
        try:
            response = self.gemini_model.generate_content(prompt)
            result_text = response.text
            return self._parse_ai_response(result_text, mail_data, urls, sources)
            
        except Exception as e:
            logger.error(f"Gemini AI 분류 중 오류: {e}")
            raise
    
    def _classify_with_openai(self, mail_data, urls=None, sources=None):
        """OpenAI API를 사용한 분류"""
        if not self.openai_client:
            raise Exception("OpenAI API가 초기화되지 않았습니다")
            
        prompt = self._create_classification_prompt(mail_data, urls, sources)
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "당신은 이메일 내용을 객관적이고 사실 중심적으로 요약하는 분석가입니다. 주관적인 평가나 추측은 하지 말고, 오직 발신자가 말한 내용, 언급된 날짜와 숫자, 사실적 정보만을 기반으로 요약하세요. '중요하다', '예상된다', '좋다/나쁘다' 같은 주관적 표현 대신 '언급했다', '발표했다', '보고했다' 등의 객관적 표현을 사용하세요. 한국어로 응답하고 JSON 형식을 정확히 따라주세요."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            result_text = response.choices[0].message.content
            return self._parse_ai_response(result_text, mail_data, urls, sources)
            
        except Exception as e:
            logger.error(f"OpenAI 분류 중 오류: {e}")
            raise
    
    def _create_classification_prompt(self, mail_data, urls=None, sources=None):
        """분류를 위한 프롬프트 생성"""
        urls = urls or []
        sources = sources or []
        
        url_info = ""
        if urls:
            url_info = f"\n\n참조 URL: {', '.join(urls)}"
        if sources:
            url_info += f"\n출처: {', '.join(sources)}"
        
        main_content = mail_data.get('content', '').strip()
        if not main_content:
            main_content = mail_data.get('subject', '')
            content_source = "제목"
        else:
            content_source = "본문"
        
        return f"""
다음 이메일을 분석하여 반드시 JSON 형식으로만 응답해주세요. 다른 설명 없이 JSON만 반환하세요:

제목: {mail_data.get('subject', '')}
날짜: {mail_data.get('date', '')}
분석 대상 {content_source}: {main_content[:2000]}{url_info}

반드시 다음과 정확히 같은 JSON 형식으로만 응답하세요:
{{
    "category": "카테고리명 (경제뉴스/기술동향/업무지시/공지사항/미팅일정/보고서/기타 중 선택)",
"이메일의 내용을 객관적 사실 중심으로 4-6문장으로 요약. 다음 요소를 반드시 포함: 1) 내용의 주제와 배경 2) 구체적 날짜, 숫자, 인명, 회사명, 지역 등 사실 정보 3) 발표된 내용, 연구 결과, 비즈니스 동향 등 핀트나 주장이 아닌 사실만 기술 4) 필요시 용어 설명. 주관적 평가(중요하다, 좋다, 나쁘다 등)나 추측은 배제하고, 대신 어떤 사실이 언급되었는지만 기술. 출처나 URL이 있다면 '출처: [URL]' 형식으로 끝에 추가",
    "tags": ["주요키워드1", "주요키워드2", "주요키워드3", "주요키워드4", "주요키워드5"],
    "action_required": true,
    "key_concepts": ["백링크용_핵심개념1", "백링크용_핵심개념2", "백링크용_핵심개념3"],
    "urls": {urls if urls else []},
    "sources": {sources if sources else []},
    "readability": "비전문가도 이해할 수 있도록 친절하고 상세하게 설명"
}}

중요 가이드라인: 
- 반드시 위의 JSON 형식으로만 응답하세요
- 다른 설명이나 텍스트는 포함하지 마세요  
- 오직 {{ }}로 시작하고 끝나는 JSON만 반환하세요
- summary는 사실만 기술하고 주관적 평가는 절대 하지 마세요
- '중요하다', '좋다', '나쁘다', '예상된다' 같은 주관적 표현 금지
- '언급했다', '발표했다', '보고했다' 등의 객관적 표현 사용
- 단순히 제목을 다시 쓰지 말고 실제 내용의 사실을 정리하세요
"""
    
    def _parse_ai_response(self, result_text, mail_data, urls=None, sources=None):
        """AI 응답을 파싱하여 결과 반환"""
        try:
            # JSON 추출 - 여러 패턴 시도
            json_result = None
            
            # 패턴 1: 기본 JSON 블록
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    json_result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            # 패턴 2: ```json 코드 블록 내부
            if not json_result:
                code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_text, re.DOTALL)
                if code_match:
                    try:
                        json_result = json.loads(code_match.group(1))
                    except json.JSONDecodeError:
                        pass
            
            # 패턴 3: 여러 줄에 걸친 JSON (탭/공백 포함)
            if not json_result:
                multiline_match = re.search(r'\{\s*"[^"]*"\s*:\s*[^}]*\}', result_text, re.DOTALL)
                if multiline_match:
                    try:
                        json_result = json.loads(multiline_match.group())
                    except json.JSONDecodeError:
                        pass
            
            if not json_result:
                # JSON을 찾지 못한 경우 응답 텍스트 로깅
                logger.warning(f"AI 응답에서 JSON을 찾을 수 없음. 응답 내용: {result_text[:200]}...")
                raise ValueError("JSON 형식을 찾을 수 없음")
            
            result = json_result
            
            # 검증 및 기본값 설정
            result['category'] = result.get('category', '기타')
            result['summary'] = result.get('summary', mail_data.get('subject', '요약 없음'))
            result['tags'] = result.get('tags', [])
            result['action_required'] = result.get('action_required', False)
            result['key_concepts'] = result.get('key_concepts', [])
            result['urls'] = result.get('urls', urls or [])
            result['sources'] = result.get('sources', sources or [])
            
            return result
            
        except Exception as e:
            logger.error(f"AI 응답 파싱 중 오류: {e}")
            # 기본 분류 결과 반환
            return {
                'category': '기타',
                'summary': mail_data.get('subject', '요약 없음'),
                'tags': [],
                'action_required': False,
                'key_concepts': [],
                'urls': urls or [],
                'sources': sources or []
            }
    
    def get_current_api(self):
        """현재 사용 중인 API 반환"""
        return self.current_api
    
    def reset_to_primary(self):
        """기본 API로 재설정"""
        self.current_api = self.primary_api
        logger.info(f"API를 기본값({self.primary_api})으로 재설정")