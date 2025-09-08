import logging
from typing import List, Optional, Tuple
import asyncio

logger = logging.getLogger(__name__)

class PaginationHandler:
    def __init__(self):
        """페이지네이션 처리기 초기화"""
        self.current_page = 1
        self.total_pages = 1
        self.items_per_page = 80  # 한 페이지당 약 80개 메일
        self.max_pages = 10  # 최대 처리할 페이지 수 (안전장치)
        
    async def detect_pagination_info(self, page) -> Tuple[int, int]:
        """현재 페이지 정보 및 총 페이지 수 감지"""
        try:
            # 패턴 1: iframe 내부의 페이지네이션 정보 찾기
            iframes = await page.query_selector_all("iframe")
            for iframe in iframes:
                try:
                    frame_content = await iframe.content_frame()
                    if frame_content:
                        # 페이지 정보 텍스트 패턴들
                        pagination_selectors = [
                            ".pagination_info, .page_info, .paging_info",
                            "[class*='page'][class*='info']",
                            ".total_count, .total_page",
                            "[class*='total'][class*='count']",
                            ".page_num, .current_page",
                            ".pagination .current, .paging .current",
                        ]
                        
                        for selector in pagination_selectors:
                            try:
                                element = await frame_content.query_selector(selector)
                                if element:
                                    text = await element.text_content()
                                    if text and ('/' in text or '페이지' in text or 'page' in text.lower()):
                                        logger.info(f"페이지 정보 발견: {text}")
                                        current, total = self._parse_pagination_text(text)
                                        if current and total:
                                            return current, total
                            except Exception:
                                continue
                                
                except Exception as e:
                    logger.debug(f"iframe 페이지 정보 추출 실패: {e}")
                    continue
            
            # 패턴 2: 메인 페이지에서 페이지네이션 정보 찾기
            main_selectors = [
                ".pagination_info, .page_info, .paging_info",
                "[class*='page'][class*='info']",
                ".total_count, .total_page",
                "[class*='total'][class*='count']",
            ]
            
            for selector in main_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.text_content()
                        if text and ('/' in text or '페이지' in text or 'page' in text.lower()):
                            logger.info(f"메인 페이지 정보 발견: {text}")
                            current, total = self._parse_pagination_text(text)
                            if current and total:
                                return current, total
                except Exception:
                    continue
            
            # 패턴 3: 메일 수를 기반으로 추정
            total_mails = await self._estimate_total_mail_count(page)
            if total_mails > 0:
                estimated_pages = max(1, (total_mails + self.items_per_page - 1) // self.items_per_page)
                logger.info(f"메일 수 기반 추정: 총 {total_mails}개 메일, {estimated_pages}페이지")
                return 1, estimated_pages
                
        except Exception as e:
            logger.error(f"페이지 정보 감지 실패: {e}")
        
        return 1, 1  # 기본값
    
    def _parse_pagination_text(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        """페이지 정보 텍스트에서 현재/총 페이지 추출"""
        try:
            text = text.strip().lower()
            
            # 패턴 1: "1 / 3" 형식
            if '/' in text:
                parts = text.split('/')
                if len(parts) == 2:
                    current = int(parts[0].strip())
                    total = int(parts[1].strip())
                    return current, total
            
            # 패턴 2: "1페이지 / 3페이지" 형식
            if '페이지' in text and '/' in text:
                parts = text.split('/')
                if len(parts) == 2:
                    current = int(parts[0].replace('페이지', '').strip())
                    total = int(parts[1].replace('페이지', '').strip())
                    return current, total
            
            # 패턴 3: "page 1 of 3" 형식
            if 'page' in text and 'of' in text:
                parts = text.split('of')
                if len(parts) == 2:
                    current = int(parts[0].replace('page', '').strip())
                    total = int(parts[1].strip())
                    return current, total
            
            # 패턴 4: "1-80 of 240" 형식 (범위/총계)
            if 'of' in text and '-' in text:
                parts = text.split('of')
                if len(parts) == 2:
                    total_items = int(parts[1].strip())
                    range_part = parts[0].strip()
                    if '-' in range_part:
                        start_num = int(range_part.split('-')[0].strip())
                        current_page = (start_num - 1) // self.items_per_page + 1
                        total_pages = (total_items + self.items_per_page - 1) // self.items_per_page
                        return current_page, total_pages
                        
        except Exception as e:
            logger.debug(f"페이지 텍스트 파싱 실패: {text} - {e}")
        
        return None, None
    
    async def _estimate_total_mail_count(self, page) -> int:
        """총 메일 수 추정"""
        try:
            # 총 메일 수 표시하는 요소들
            count_selectors = [
                ".total_count .num, .total_count .number",
                "[class*='total'][class*='count'] .num",
                ".mail_count, .message_count",
                "[class*='mail'][class*='count']",
                ".count_info .num",
            ]
            
            # iframe부터 검사
            iframes = await page.query_selector_all("iframe")
            for iframe in iframes:
                try:
                    frame_content = await iframe.content_frame()
                    if frame_content:
                        for selector in count_selectors:
                            try:
                                element = await frame_content.query_selector(selector)
                                if element:
                                    text = await element.text_content()
                                    if text and text.strip().isdigit():
                                        count = int(text.strip())
                                        if count > 0:
                                            return count
                            except Exception:
                                continue
                except Exception:
                    continue
            
            # 메인 페이지에서 검사
            for selector in count_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.text_content()
                        if text and text.strip().isdigit():
                            count = int(text.strip())
                            if count > 0:
                                return count
                except Exception:
                    continue
                    
        except Exception as e:
            logger.debug(f"메일 수 추정 실패: {e}")
        
        return 0
    
    async def is_clickable_element(self, element) -> bool:
        """더 유연한 클릭 가능성 판단"""
        try:
            # 기본 가시성 체크
            is_visible = await element.is_visible()
            if not is_visible:
                return False
                
            # disabled 속성이 명시적으로 true가 아닌 경우 클릭 가능으로 간주
            disabled_attr = await element.get_attribute('disabled')
            class_attr = await element.get_attribute('class') or ""
            
            # 명시적 비활성화 패턴 체크
            if (disabled_attr == "true" or 
                "disabled" in class_attr.lower() or 
                "inactive" in class_attr.lower()):
                return False
                
            # evt-rol 패턴은 특별히 우선 처리
            evt_rol = await element.get_attribute('evt-rol')
            if evt_rol == 'list-page-move':
                text = await element.text_content()
                return text and text.strip().isdigit()  # 숫자 페이지는 클릭 가능
                
            return True
            
        except Exception:
            return False
    
    async def has_next_page(self, page) -> bool:
        """다음 페이지가 있는지 확인 (강화된 감지)"""
        try:
            logger.info(f"🔍 다음 페이지 존재 여부 확인 중... (현재: {self.current_page}/{self.total_pages})")
            
            # 다음 페이지 버튼 선택자들 (우선순위 조정)
            next_selectors = [
                # evt-rol 패턴 우선 처리 (실제 에러 로그에서 발견된 패턴)
                f"a[evt-rol='list-page-move'][text='{self.current_page + 1}']",
                "a[evt-rol='list-page-move']",
                f"a[page='{self.current_page + 1}']",
                
                # 정확한 구조 매칭
                "a.next.paginate_button[title='다음']",
                "a.next.paginate_button",
                "a[class*='next'][class*='paginate_button']",
                "a[evt-rol='list-page-move'][title='다음']",
                
                # 기존 일반적인 패턴들
                ".next:not(.disabled):not([disabled])",
                ".next_page:not(.disabled):not([disabled])", 
                "[class*='next']:not([class*='disabled']):not([disabled])",
                ".pagination .next:not(.disabled):not([disabled])",
                ".paging .next:not(.disabled):not([disabled])",
                "button[title*='다음']:not([disabled])",
                "a[title*='다음']:not(.disabled)",
                "a[href*='page=']:not(.disabled)",
                ".page_next:not(.disabled):not([disabled])",
                "[class*='arrow'][class*='right']:not(.disabled):not([disabled])",
                
                # 추가 패턴들
                "img[alt*='다음']:not(.disabled)",
                "input[value*='다음']:not([disabled])",
                "[onclick*='next']:not(.disabled):not([disabled])",
                "[onclick*='다음']:not(.disabled):not([disabled])",
                
                # 숫자 페이지네이션
                f"a[href*='page={self.current_page + 1}']",
                f"button[data-page='{self.current_page + 1}']",
            ]
            
            found_elements = []
            
            # iframe에서 먼저 검사
            iframes = await page.query_selector_all("iframe")
            for i, iframe in enumerate(iframes):
                try:
                    frame_content = await iframe.content_frame()
                    if frame_content:
                        logger.info(f"🔍 iframe[{i}]에서 다음 페이지 버튼 검색 중...")
                        
                        for selector in next_selectors:
                            try:
                                elements = await frame_content.query_selector_all(selector)
                                for element in elements:
                                    is_clickable = await self.is_clickable_element(element)
                                    text = await element.text_content() or ""
                                    is_visible = await element.is_visible()
                                    
                                    element_info = {
                                        'selector': selector,
                                        'visible': is_visible,
                                        'clickable': is_clickable,
                                        'text': text.strip()[:20],
                                        'location': f'iframe[{i}]'
                                    }
                                    found_elements.append(element_info)
                                    
                                    if is_clickable:
                                        logger.info(f"✅ 다음 페이지 버튼 발견: {selector} (텍스트: '{text.strip()[:20]}')")
                                        return True
                                        
                            except Exception as e:
                                logger.debug(f"선택자 {selector} 검사 실패: {e}")
                                continue
                except Exception as e:
                    logger.debug(f"iframe[{i}] 접근 실패: {e}")
                    continue
            
            # 메인 페이지에서 검사
            logger.info("🔍 메인 페이지에서 다음 페이지 버튼 검색 중...")
            for selector in next_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        is_clickable = await self.is_clickable_element(element)
                        text = await element.text_content() or ""
                        is_visible = await element.is_visible()
                        
                        element_info = {
                            'selector': selector,
                            'visible': is_visible,
                            'clickable': is_clickable,
                            'text': text.strip()[:20],
                            'location': 'main_page'
                        }
                        found_elements.append(element_info)
                        
                        if is_clickable:
                            logger.info(f"✅ 메인 페이지 다음 버튼 발견: {selector} (텍스트: '{text.strip()[:20]}')")
                            return True
                except Exception as e:
                    logger.debug(f"메인 페이지 선택자 {selector} 검사 실패: {e}")
                    continue
            
            # 발견된 모든 요소 디버깅 정보 출력
            logger.warning(f"❌ 활성화된 다음 페이지 버튼을 찾을 수 없습니다.")
            logger.info(f"🔍 발견된 페이지네이션 관련 요소들 ({len(found_elements)}개):")
            for elem in found_elements:
                status = "✅클릭가능" if elem.get('clickable', False) else "❌비활성"
                logger.info(f"  - {status} | {elem['location']} | {elem['selector'][:30]} | '{elem['text']}'")
            
            # 총 페이지 정보와 비교 체크
            if self.total_pages > 1 and self.current_page < self.total_pages:
                logger.warning(f"⚠️ 페이지 정보 불일치: 현재 {self.current_page}/{self.total_pages} - 다음 페이지가 있어야 함")
                logger.info("🔄 페이지 정보 기반으로 다음 페이지 존재한다고 판단")
                return True
                
        except Exception as e:
            logger.error(f"다음 페이지 확인 실패: {e}")
        
        # 마지막 폴백: 첫 페이지에서 충분한 메일이 있으면 다음 페이지 강제 시도
        if self.current_page == 1:
            logger.info("🔄 첫 페이지에서 페이지네이션 버튼을 찾지 못했지만, 추가 페이지가 있을 수 있음")
            logger.info("📊 메일 수 기반 다음 페이지 존재 가능성 판단")
            return True  # 첫 페이지에서는 시도해보기
        
        return False
    
    async def go_to_next_page(self, page) -> bool:
        """다음 페이지로 이동"""
        try:
            # 다음 페이지 버튼 클릭 시도 (실제 HTML 구조 기반)
            next_selectors = [
                # 정확한 구조 매칭 (우선순위)
                "a.next.paginate_button[title='다음']",
                "a.next.paginate_button",
                "a[class*='next'][class*='paginate_button']",
                f"a[page='{self.current_page + 1}']",
                "a[evt-rol='list-page-move'][title='다음']",
                "a[evt-rol='list-page-move']",
                
                # 기존 패턴들
                ".next:not(.disabled)",
                ".next_page:not(.disabled)", 
                "[class*='next']:not([class*='disabled'])",
                ".pagination .next:not(.disabled)",
                ".paging .next:not(.disabled)",
                "button[title*='다음']:not([disabled])",
                "a[title*='다음']:not(.disabled)",
                ".page_next:not(.disabled)",
                "[class*='arrow'][class*='right']:not(.disabled)",
            ]
            
            # iframe에서 먼저 시도
            iframes = await page.query_selector_all("iframe")
            for iframe in iframes:
                try:
                    frame_content = await iframe.content_frame()
                    if frame_content:
                        for selector in next_selectors:
                            try:
                                element = await frame_content.query_selector(selector)
                                if element:
                                    is_clickable = await self.is_clickable_element(element)
                                    if is_clickable:
                                        logger.info(f"다음 페이지 버튼 클릭 시도: {selector}")
                                        
                                        # 클릭 전 현재 URL 저장
                                        current_url = page.url
                                        
                                        try:
                                            # 일반 클릭 시도
                                            await element.click(timeout=5000)
                                        except Exception as click_error:
                                            logger.info(f"일반 클릭 실패, JavaScript 클릭 시도: {click_error}")
                                            # JavaScript 클릭으로 대체
                                            await frame_content.evaluate("(element) => element.click()", element)
                                        
                                        await page.wait_for_timeout(2000)  # 페이지 로딩 대기
                                        
                                        # 페이지 변화 확인
                                        try:
                                            await page.wait_for_load_state('networkidle', timeout=10000)
                                        except:
                                            # 네트워크 대기 실패해도 계속 진행
                                            pass
                                        
                                        logger.info("✅ iframe 다음 페이지 이동 성공")
                                        self.current_page += 1
                                        return True
                            except Exception as e:
                                logger.debug(f"iframe 다음 페이지 클릭 실패 {selector}: {e}")
                                continue
                except Exception:
                    continue
            
            # 메인 페이지에서 시도
            for selector in next_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        is_clickable = await self.is_clickable_element(element)
                        if is_clickable:
                            logger.info(f"메인 페이지 다음 버튼 클릭 시도: {selector}")
                            
                            current_url = page.url
                            
                            try:
                                # 일반 클릭 시도
                                await element.click(timeout=5000)
                            except Exception as click_error:
                                logger.info(f"메인 페이지 일반 클릭 실패, JavaScript 클릭 시도: {click_error}")
                                # JavaScript 클릭으로 대체
                                await page.evaluate("(element) => element.click()", element)
                            
                            await page.wait_for_timeout(2000)
                            
                            try:
                                await page.wait_for_load_state('networkidle', timeout=10000)
                            except:
                                # 네트워크 대기 실패해도 계속 진행
                                pass
                            
                            logger.info("✅ 메인 페이지 다음 페이지 이동 성공")
                            self.current_page += 1
                            return True
                except Exception as e:
                    logger.debug(f"메인 다음 페이지 클릭 실패 {selector}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"다음 페이지 이동 실패: {e}")
        
        return False
    
    async def wait_for_page_load(self, page, timeout=10000):
        """페이지 로딩 완료 대기"""
        try:
            await page.wait_for_load_state('networkidle', timeout=timeout)
            await page.wait_for_timeout(1000)  # 추가 안정화 대기
            logger.info("페이지 로딩 완료")
            return True
        except Exception as e:
            logger.warning(f"페이지 로딩 대기 실패: {e}")
            return False
    
    def should_continue_pagination(self, current_mails_count: int, max_mails: Optional[int] = None) -> bool:
        """페이지네이션을 계속할지 판단"""
        # 최대 페이지 수 제한
        if self.current_page >= self.max_pages:
            logger.warning(f"최대 페이지 수 도달 ({self.max_pages}페이지)")
            return False
        
        # 최대 메일 수 제한 (테스트 모드)
        if max_mails and current_mails_count >= max_mails:
            logger.info(f"최대 메일 수 도달 ({current_mails_count}/{max_mails})")
            return False
        
        return True
    
    def get_pagination_info(self) -> dict:
        """현재 페이지네이션 정보 반환"""
        return {
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "items_per_page": self.items_per_page,
            "max_pages": self.max_pages
        }