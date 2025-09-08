import asyncio
from playwright.async_api import async_playwright
import logging
from datetime import datetime
import time
import re
from pagination_handler import PaginationHandler

logger = logging.getLogger(__name__)

class MailCollector:
    def __init__(self, username, password, target_folder, headless=True):
        """메일 수집기 초기화"""
        self.username = username
        self.password = password
        self.target_folder = target_folder
        self.base_url = "https://tekville.daouoffice.com"
        self.headless = headless
        self.pagination_handler = PaginationHandler()
        
    def collect_mails(self, process_all=False, test_mode=False, processed_mails=None):
        """메일 수집 메인 함수"""
        return asyncio.run(self._collect_mails_async(process_all, test_mode, processed_mails))
    
    async def _collect_mails_async(self, process_all, test_mode, processed_mails):
        """비동기 메일 수집"""
        processed_mails = processed_mails or []
        mails = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                # 로그인
                logger.info("Dauoffice 로그인 시도...")
                await self._login(page)
                
                # 대상 폴더로 이동
                logger.info(f"'{self.target_folder}' 폴더로 이동...")
                await self._navigate_to_folder(page)
                
                # 메일 목록 수집
                logger.info("메일 목록 수집 중...")
                mails = await self._collect_mail_list_new(page, process_all, test_mode, processed_mails)
                
                logger.info(f"총 {len(mails)}개 메일 수집 완료")
                
            except Exception as e:
                logger.error(f"메일 수집 중 오류: {e}")
                raise
            finally:
                await browser.close()
        
        return mails
    
    async def _login(self, page):
        """로그인 처리"""
        await page.goto(f"{self.base_url}/login?returnUrl=%2Fapp%2Fmail")
        
        # ID 입력
        await page.wait_for_selector('//*[@id="username"]')
        await page.fill('//*[@id="username"]', self.username)
        
        # PW 입력
        await page.fill('//*[@id="password"]', self.password)
        
        # 로그인 클릭
        await page.click('//*[@id="login_submit"]')
        
        # 로그인 후 페이지 전환 대기
        try:
            # URL 변경을 기다리기 (로그인 성공 시 URL이 바뀐)
            await page.wait_for_url('**/app/mail**', timeout=15000)
            logger.info("로그인 성공 - 메일 페이지로 이동")
        except Exception as e:
            logger.warning(f"URL 변경 대기 실패, 대안 방법 시도: {e}")
            # 대안: load state 대기
            try:
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                await asyncio.sleep(2)
            except:
                logger.warning("대안 대기도 실패, 계속 진행")
        
        await asyncio.sleep(2)  # 추가 안정화 대기
        
        # 로그인 확인 (문자열 포함 체크로 변경)
        current_url = page.url.lower()
        if "login" in current_url and "app" not in current_url:
            raise Exception("로그인 실패: 아이디 또는 비밀번호를 확인해주세요.")
        
        logger.info(f"로그인 성공 - 현재 URL: {page.url}")
    
    async def _navigate_to_folder(self, page):
        """대상 폴더로 이동 - iframe 내부 검색 집중"""
        logger.info(f"'{self.target_folder}' 폴더 찾기 시작 (iframe 내부 검색)...")
        
        # iframe 내부에서 폴더 찾기 (실제로 작동하는 유일한 방법)
        try:
            logger.info("iframe 내부에서 폴더 찾기...")
            
            # 모든 iframe 찾기
            iframes = await page.query_selector_all("iframe")
            logger.info(f"발견된 iframe 수: {len(iframes)}")
            
            for frame_idx, iframe_element in enumerate(iframes):
                try:
                    frame_name = await iframe_element.get_attribute("name") or f"frame_{frame_idx}"
                    frame_src = await iframe_element.get_attribute("src") or "no-src"
                    logger.info(f"  iframe {frame_idx}: name='{frame_name}', src='{frame_src}'")
                    
                    # iframe 내부 접근
                    frame_content = await iframe_element.content_frame()
                    if frame_content:
                        logger.info(f"    iframe 내부 접근 성공")
                        
                        # iframe 내부에서 get_by_text() 시도
                        try:
                            iframe_folder_locator = frame_content.get_by_text(self.target_folder)
                            await iframe_folder_locator.wait_for(timeout=10000)
                            await iframe_folder_locator.click()
                            
                            logger.info(f"✅ iframe 내부에서 '{self.target_folder}' 폴더 클릭 성공!")
                            
                            # 더 관대한 대기 조건 적용
                            try:
                                # 1차: networkidle 대기 (5초로 단축)
                                await page.wait_for_load_state('networkidle', timeout=5000)
                            except:
                                try:
                                    # 2차: domcontentloaded 대기
                                    await page.wait_for_load_state('domcontentloaded', timeout=5000)
                                except:
                                    # 3차: 단순 시간 대기
                                    await asyncio.sleep(3)
                            
                            logger.info(f"✅ '{self.target_folder}' 폴더 로딩 완료!")
                            return
                            
                        except Exception as iframe_click_e:
                            # 클릭은 성공했지만 대기에서 실패한 경우 체크
                            if "클릭 성공" in str(iframe_click_e):
                                logger.info(f"클릭은 성공했으나 대기 실패: {iframe_click_e}")
                                # 폴더가 실제로 열렸는지 확인
                                try:
                                    # 메일 목록이 나타났는지 확인
                                    mail_list_check = await page.query_selector(".mail_list, .message_list, [class*='mail'][class*='list']")
                                    if mail_list_check:
                                        logger.info("✅ 메일 목록 발견! 폴더 열기 성공으로 간주")
                                        return
                                except:
                                    pass
                            
                            logger.warning(f"    iframe 내부 클릭 실패: {iframe_click_e}")
                        
                except Exception as iframe_e:
                    logger.warning(f"  iframe {frame_idx} 접근 실패: {iframe_e}")
                    
        except Exception as e:
            logger.warning(f"iframe 검사 실패: {e}")
        
        # iframe에서 실패한 경우 디버깅 정보 수집
        try:
            logger.info("=== iframe 내부 디버깅 정보 수집 ===")
            
            for frame_idx, iframe_element in enumerate(iframes):
                try:
                    frame_content = await iframe_element.content_frame()
                    if frame_content:
                        # iframe 내부의 모든 텍스트 요소 수집
                        iframe_texts = await frame_content.locator("*").filter(has_text=re.compile(r".+")).all_inner_texts()
                        iframe_unique_texts = list(set([text.strip() for text in iframe_texts if text and len(text.strip()) < 50]))[:15]
                        
                        logger.info(f"iframe {frame_idx} 내부 텍스트 요소들:")
                        for i, text in enumerate(iframe_unique_texts, 1):
                            logger.info(f"    {i}. '{text}'")
                        
                        # 'z'로 시작하는 텍스트 확인
                        z_texts = [text for text in iframe_unique_texts if text.startswith('z')]
                        if z_texts:
                            logger.info(f"iframe {frame_idx}에서 'z'로 시작하는 텍스트들: {z_texts}")
                            
                except Exception as debug_e:
                    logger.warning(f"iframe {frame_idx} 디버깅 실패: {debug_e}")
            
        except Exception as debug_e:
            logger.warning(f"iframe 디버깅 정보 수집 실패: {debug_e}")
        
        # 최종 실패
        logger.error(f"'{self.target_folder}' 폴더를 찾을 수 없습니다.")
        logger.info("💡 해결 방법:")
        logger.info("1. GUI에서 '실행과정 관찰하기' 체크박스를 선택하여 브라우저에서 실제 폴더 이름을 확인하세요")
        logger.info("2. 설정에서 폴더명을 '받은편지함'으로 변경해보세요 (기본 메일함)")
        logger.info("3. iframe 디버깅 로그에서 발견된 폴더 중 하나를 사용하세요")
        raise Exception(f"'{self.target_folder}' 폴더를 찾을 수 없습니다.")
    
    async def _collect_mail_list(self, page, process_all, test_mode, processed_mails):
        """메일 목록 수집 - iframe 내부 검색 우선"""
        mails = []
        
        # 메일 리스트 선택자들 (성공률 높은 순서)
        mail_list_selectors = [
            '.mail_list',           # 가장 일반적
            'table.mail_list',      # 테이블 형태
            'tbody tr[id*="_"]',     # 메일 행 직접 찾기
            '.message_list', 
            '.email_list',
            '[class*="mail"][class*="list"]',
            '[class*="message"][class*="list"]',
            '.list_wrap table',
            '#mailListTable'
        ]
        
        mail_list_found = False
        
        # 1차: iframe 내부 검색 우선 (빠른 성공률)
        logger.info("iframe 내부에서 메일 목록 검색 중...")
        try:
            iframes = await page.query_selector_all("iframe")
            for iframe_element in iframes:
                frame_content = await iframe_element.content_frame()
                if frame_content:
                    for selector in mail_list_selectors:
                        try:
                            await frame_content.wait_for_selector(selector, timeout=1000)  # 1초만 대기
                            logger.info(f"✅ iframe 내부에서 메일 목록 발견: {selector}")
                            mail_list_found = True
                            break
                        except:
                            continue
                    if mail_list_found:
                        break
        except Exception as e:
            logger.warning(f"iframe 내부 메일 목록 검색 실패: {e}")
        
        # 2차: 표준 선택자 검색 (iframe 실패시에만)
        if not mail_list_found:
            logger.info("표준 메일 목록 선택자로 검색 중...")
            for selector in mail_list_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)  # 2초만 대기
                    logger.info(f"✅ 메일 목록 발견: {selector}")
                    mail_list_found = True
                    break
                except:
                    continue
        
        # 메일 행 선택자들 (실제 HTML 구조 기반으로 수정)
        mail_row_selectors = [
            # 실제 메일 행만 선택 (날짜 헤더 제외)
            "table.mail_list.list_mail001 tbody tr[id*='&']",  # 실제 메일 ID 패턴 (z&x3TWFcE4-_3758)
            "table.mail_list tbody tr[id*='&']",               # 백업 선택자
            "table.mail_list.list_mail001 tbody tr[id*='_']:not([id*='dateDesc'])",  # dateDesc 제외
            "table.mail_list tbody tr[id*='_']:not([id*='dateDesc'])",  # dateDesc 제외
            "tbody tr[id*='Inbox_']",                          # 받은편지함 특화
            "tbody tr[id*='_']:not([id*='dateDesc'])",         # dateDesc 제외
            ".mail_list tr[id*='_']:not([id*='dateDesc'])",    # 클래스 기반
            "table tbody tr[id*='_']:not([id*='dateDesc'])",   # 일반 테이블 행
            "tr[id*='Inbox']",                                 # 받은편지함 행
            "tr[id*='mail']",
            "tr[id*='message']", 
            ".message_list tr",
            "[class*='mail'][class*='row']",
            "[class*='message'][class*='row']"
        ]
        
        mail_rows = []
        frame_content = None
        
        # 1차: iframe 내부에서 메일 행 검색 (빠른 성공률)
        logger.info("iframe 내부에서 메일 행 검색 중...")
        try:
            iframes = await page.query_selector_all("iframe")
            for iframe_element in iframes:
                frame_content = await iframe_element.content_frame()
                if frame_content:
                    for selector in mail_row_selectors:
                        try:
                            rows = await frame_content.query_selector_all(selector)
                            if rows:
                                logger.info(f"✅ iframe 내부에서 메일 행 발견: {selector} ({len(rows)}개)")
                                mail_rows = rows
                                break
                        except:
                            continue
                    if mail_rows:
                        break
            if not mail_rows:
                frame_content = None  # 메일 행을 찾지 못한 경우
        except Exception as e:
            logger.warning(f"iframe 내부 메일 행 검색 실패: {e}")
            frame_content = None
        
        # 2차: 메인 페이지에서 메일 행 검색 (iframe 실패시에만)
        if not mail_rows:
            logger.info("메인 페이지에서 메일 행 검색 중...")
            for selector in mail_row_selectors:
                try:
                    rows = await page.query_selector_all(selector)
                    if rows:
                        logger.info(f"✅ 메일 행 발견: {selector} ({len(rows)}개)")
                        mail_rows = rows
                        break
                except Exception as e:
                    logger.warning(f"메일 행 선택자 '{selector}' 실패: {e}")
                    continue
        
        if not mail_rows:
            logger.error("메일 행을 전혀 찾을 수 없습니다. 빈 메일함이거나 다른 문제가 있을 수 있습니다.")
            return []
        
        logger.info(f"전체 행 수: {len(mail_rows)}, process_all: {process_all}, test_mode: {test_mode}")
        
        processed_count = 0  # 실제로 처리된 메일 개수 (중복 스킵 제외)
        max_process = 5 if test_mode else float('inf')  # 테스트 모드일 때 최대 5개까지
        test_attempt_count = 0  # 테스트 모드에서 시도한 메일 개수
        
        logger.debug(f"루프 시작 - 총 {len(mail_rows)}개 행, 테스트 모드: {test_mode}")
        
        # 테스트 모드에서는 5개만 처리하도록 루프 제한
        max_loop = 5 if test_mode else len(mail_rows)
        
        for row_index in range(max_loop):
            logger.debug(f"루프 {row_index + 1}/{max_loop} 시작")
            try:
                # 메일 목록이 로드되었는지 먼저 확인
                if frame_content:
                    if not await self.wait_for_mail_list_loaded(frame_content, expected_count=1, max_wait=5):
                        logger.warning(f"🔍 진실의 방: 루프 {row_index + 1} - 메일 목록 로딩 실패 - 스킵")
                        continue
                
                # 각 루프마다 새로운 행 요소 찾기 (DOM 변경 대응)
                try:
                    logger.debug(f"새로운 행 검색 시작")
                    
                    # iframe에서 현재 인덱스의 행을 다시 찾기
                    if frame_content:
                        current_rows = await frame_content.query_selector_all("table.mail_list.list_mail001 tbody tr[id*='&']")
                        logger.debug(f"iframe에서 {len(current_rows)}개 행 발견")
                    else:
                        current_rows = await page.query_selector_all("table.mail_list.list_mail001 tbody tr[id*='&']")
                        logger.debug(f"메인 페이지에서 {len(current_rows)}개 행 발견")
                    
                    if row_index >= len(current_rows):
                        logger.warning(f"행 인덱스 {row_index}가 현재 행 수 {len(current_rows)}를 초과 - 스킵")
                        continue
                    
                    row = current_rows[row_index]
                    logger.debug(f"행 요소 선택 완료")
                    
                    # 요소 유효성 확인
                    # DOM 존재 여부로 가시성 확인 (is_visible() 대신)
                    # 메일 행이 DOM에 존재하면 처리 진행
                    try:
                        row_id = await row.get_attribute('id')
                        if row_id:  # ID가 존재하면 DOM에 요소가 존재하는 것으로 판단
                            logger.debug(f"DOM에 행 존재 확인, 처리 진행")
                        else:
                            logger.warning(f"행 ID 없음 - 스킵")
                            continue
                    except Exception as e:
                        logger.warning(f"행 접근 실패: {e} - 스킵")
                        continue
                    
                    logger.debug(f"메일 ID 추출 시도")
                    mail_id = await row.get_attribute('id')
                    if not mail_id:
                        logger.warning(f"메일 ID를 가져올 수 없음 - 스킵")
                        continue
                    
                    logger.debug(f"메일 ID 추출 성공: {mail_id}")
                        
                except Exception as e:
                    logger.warning(f"요소 접근 실패: {e}")
                    continue
                    
                logger.debug(f"메일 행 처리 중: ID={mail_id}")
                
                # 날짜 헤더 스킵 (dateDesc_로 시작하는 ID는 날짜 헤더)
                if mail_id and mail_id.startswith('dateDesc_'):
                    logger.debug(f"날짜 헤더 스킵: {mail_id}")
                    continue
                
                # 중복 체크 개선 - 테스트 모드에서는 중복도 처리
                is_duplicate = False
                if not process_all and processed_mails and not test_mode:  # 테스트 모드에서는 중복 체크 스킵
                    # 최근 100개 메일만 중복 체크 (전체 기록 대신)
                    recent_processed = processed_mails[-100:] if len(processed_mails) > 100 else processed_mails
                    is_duplicate = mail_id in recent_processed
                
                if is_duplicate and not test_mode:  # 테스트 모드에서는 중복도 처리
                    logger.info(f"중복 메일 스킵: {mail_id} (최근 100개 중 발견)")
                    continue  # 중복 메일은 processed_count에 포함하지 않음
                elif process_all:
                    logger.debug(f"모든 메일 처리 모드: {mail_id}")
                elif test_mode:
                    test_attempt_count += 1  # 먼저 증가
                    logger.debug(f"테스트 모드 - {mail_id} (시도 {test_attempt_count}/5)")
                    logger.debug(f"현재 카운트 - test_attempt_count: {test_attempt_count}, processed_count: {processed_count}")
                else:
                    logger.debug(f"신규 메일 처리: {mail_id}")
                
                # 메일 상세 페이지로 이동하여 정보 추출
                mail_data = None
                try:
                    # 메일 클릭하여 상세 페이지로 이동
                    mail_data = await self._extract_mail_info(page, row, mail_id, frame_content)

                except Exception as mail_e:
                    logger.warning(f"메일 추출 오류: {mail_e}")
                    mail_data = None
                
                # 메일 데이터 처리
                if mail_data:
                    mails.append(mail_data)
                    processed_count += 1  # 실제 수집된 메일 개수 증가
                    logger.info(f"✅ 메일 수집 성공: {mail_data.get('subject', '제목 없음')[:30]}...")
                else:
                    # 폴백: 목록에서 기본 정보 추출
                    logger.warning(f"상세 추출 실패, 목록에서 기본 정보 추출 시도: {mail_id}")
                    try:
                        # 새로운 행 요소 찾기 (기존 요소가 detached된 경우)
                        fresh_row = None
                        try:
                            row_id = await row.get_attribute('id')
                            if row_id:
                                fresh_row = row  # 기존 요소가 여전히 유효함
                            else:
                                raise Exception("Row ID not found")
                        except:
                            # 새로운 행 요소 찾기
                            fresh_rows = await page.query_selector_all("table.mail_list tbody tr[id*='_']")
                            if frame_content:
                                iframe_rows = await frame_content.query_selector_all("table.mail_list tbody tr[id*='_']")
                                if iframe_rows:
                                    fresh_rows = iframe_rows
                            
                            for fresh_candidate in fresh_rows:
                                try:
                                    candidate_id = await fresh_candidate.get_attribute('id')
                                    if candidate_id == mail_id:
                                        fresh_row = fresh_candidate
                                        break
                                except:
                                    continue
                        
                        if fresh_row:
                            fallback_data = await self._extract_mail_info_from_list_row_safe(page, fresh_row, mail_id, frame_content)
                            if fallback_data:
                                mails.append(fallback_data)
                                processed_count += 1  # 실제 수집된 메일 개수 증가
                                logger.info(f"✅ 목록에서 메일 수집: {fallback_data.get('subject', '제목 없음')[:30]}...")
                        else:
                            logger.warning(f"새로운 행 요소를 찾을 수 없음: {mail_id}")
                            
                    except Exception as fallback_e:
                        logger.warning(f"목록 추출도 실패: {fallback_e}")
                
                # 첫 번째 메일 처리 완료 - 목록 버튼으로 이미 복귀했으므로 추가 작업 불필요
                
                # 테스트 모드에서는 루프가 5개로 제한되어 있으므로 별도 중단 조건 불필요
                
                logger.debug(f"루프 {row_index + 1} 완료 - 다음 루프로 진행")
                
            except Exception as e:
                logger.warning(f"루프 {row_index + 1} 예외 발생: {e}")
                continue
        
        logger.info(f"최종 결과 - 총 {len(mail_rows)}개 행 중 {processed_count}개 수집 완료")
        return mails
    
    async def _recover_from_frame_detached(self, page):
        """아이프레임 분리 상황에서 복구"""
        try:
            logger.info("아이프레임 분리 복구 시도...")
            # 메일 페이지로 다시 이동
            await page.goto('https://tekville.daouoffice.com/app/mail', timeout=30000)
            await asyncio.sleep(3)
            # 폴더로 다시 이동
            await self._navigate_to_folder(page)
            logger.info("아이프레임 복구 완료")
        except Exception as e:
            logger.error(f"아이프레임 복구 실패: {e}")
            raise
    
    async def wait_for_mail_list_loaded(self, frame_content, expected_count=80, max_wait=30):
        """메일 목록이 완전히 로드될 때까지 동적 대기"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                # 메일 행 검색
                current_rows = await frame_content.query_selector_all("table.mail_list.list_mail001 tbody tr[id*='&']")
                
                if len(current_rows) >= expected_count:
                    logger.info(f"✅ 메일 목록 로딩 완료: {len(current_rows)}개 행 발견")
                    return True
                elif len(current_rows) > 0:
                    logger.info(f"⏳ 메일 목록 로딩 중: {len(current_rows)}개 행 발견 (대기 중...)")
                else:
                    logger.info(f"⏳ 메일 목록 로딩 중: 행 없음 (대기 중...)")
                    
            except Exception as e:
                logger.warning(f"메일 목록 검색 중 오류: {e}")
                
            await asyncio.sleep(1)  # 1초마다 재시도
        
        logger.warning(f"⚠️ 메일 목록 로딩 타임아웃: {max_wait}초 후에도 {expected_count}개 미만")
        return False

    async def _get_mail_frame(self, page):
        """메일 목록 iframe을 안정적으로 찾아서 고정"""
        try:
            iframes = await page.query_selector_all("iframe")
            for el in iframes:
                fr = await el.content_frame()
                if fr and await fr.query_selector("table.mail_list, .mail_list, .message_list"):
                    logger.info("✅ 메일 목록 iframe 발견 및 고정")
                    return fr
            raise RuntimeError("메일 목록 iframe을 찾지 못했습니다.")
        except Exception as e:
            logger.error(f"iframe 찾기 실패: {e}")
            return None

    async def _get_mail_frame_content(self, page):
        """메일 목록 iframe 내용을 안전하게 가져오기 (기존 호환성 유지)"""
        return await self._get_mail_frame(page)

    async def _load_all_rows(self, frame, max_rounds=50):
        """가상 스크롤로 모든 메일 행을 미리 로드"""
        try:
            # 목록 컨테이너 찾기
            container = await frame.query_selector(".mail_list_wrap, .list_wrap, .list_body, table.mail_list")
            if not container:
                container = await frame.query_selector("body")
            
            # 메일 행 로케이터 (날짜 헤더 제외)
            row_loc = frame.locator("table.mail_list tbody tr[id]:not([id^='dateDesc'])")
            
            prev = -1
            rounds = 0
            
            logger.info("🔄 가상 스크롤로 모든 메일 행 로드 시작")
            
            while rounds < max_rounds:
                count = await row_loc.count()
                logger.info(f"🔄 스크롤 라운드 {rounds + 1}: {count}개 행 발견")
                
                if count == prev:  # 더 이상 증가 없음 → 완료
                    logger.info(f"✅ 모든 행 로드 완료: {count}개 행")
                    break
                    
                prev = count
                # 맨 아래로 스크롤
                await frame.evaluate("(c)=>c.scrollTo(0,c.scrollHeight)", container)
                await frame.wait_for_timeout(300)  # 렌더 대기
                rounds += 1
            
            final_count = await row_loc.count()
            logger.info(f"🎯 최종 로드된 메일 행 수: {final_count}개")
            return final_count
            
        except Exception as e:
            logger.error(f"가상 스크롤 로드 실패: {e}")
            return 0

    async def _ensure_visible(self, frame, row):
        """메일 행을 확실히 보이게 만들기 (CSS 상태 무시)"""
        try:
            rid = await row.get_attribute("id")
            if rid:
                # CSS 선택 상태 강제 해제
                await frame.evaluate(f"""
                    const row = document.querySelector('tr[id="{rid}"]');
                    if (row) {{
                        // 모든 선택 상태 클래스 제거
                        row.classList.remove('ui-draggable', 'choice', 'selected', 'active', 'on', 'current', 'focus', 'highlight');
                        // 스타일 강제 적용
                        row.style.display = 'table-row';
                        row.style.visibility = 'visible';
                        row.style.opacity = '1';
                        // 스크롤하여 보이게 만들기
                        row.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                    }}
                """)
                await frame.wait_for_timeout(100)  # 렌더 대기
                logger.debug(f"✅ 행 가시화 완료: {rid}")
                return True
        except Exception as e:
            logger.warning(f"행 가시화 실패: {e}")
        return False

    async def _open_mail_detail(self, page, frame, row):
        """메일 상세보기 열기 (CSS 상태 무시 + 강제 클릭)"""
        try:
            # 1. 행을 확실히 보이게 만들기
            await self._ensure_visible(frame, row)

            # 2. JavaScript로 직접 클릭 (Playwright 우회)
            rid = await row.get_attribute("id")
            if not rid:
                logger.warning("행 ID 없음")
                return None

            pages_before = len(page.context.pages)
            
            # JavaScript로 직접 클릭 시도
            try:
                await frame.evaluate(f"""
                    const row = document.querySelector('tr[id="{rid}"]');
                    if (row) {{
                        // 제목 셀 찾기
                        const subjectCell = row.querySelector('td.subject, td.subject a, td[evt-rol="read-message"]');
                        if (subjectCell) {{
                            // 클릭 이벤트 생성 및 실행
                            const clickEvent = new MouseEvent('click', {{
                                view: window,
                                bubbles: true,
                                cancelable: true,
                                clientX: subjectCell.offsetLeft + subjectCell.offsetWidth/2,
                                clientY: subjectCell.offsetTop + subjectCell.offsetHeight/2
                            }});
                            subjectCell.dispatchEvent(clickEvent);
                        }} else {{
                            // 폴백: 행 전체 클릭
                            const clickEvent = new MouseEvent('click', {{
                                view: window,
                                bubbles: true,
                                cancelable: true,
                                clientX: row.offsetLeft + row.offsetWidth/2,
                                clientY: row.offsetTop + row.offsetHeight/2
                            }});
                            row.dispatchEvent(clickEvent);
                        }}
                    }}
                """)
                logger.info(f"✅ JavaScript 클릭 성공: {rid}")
            except Exception as js_e:
                logger.warning(f"JavaScript 클릭 실패, Playwright 클릭 시도: {js_e}")
                # 폴백: Playwright 클릭
                title = row.locator("td.subject a, td.subject .subject, td.subject")
                if await title.count() == 0:
                    title = row
                await title.first.click(timeout=3000, force=True)

            await page.wait_for_timeout(500)
            pages_after = len(page.context.pages)
            return "popup" if pages_after > pages_before else "same"
            
        except Exception as e:
            logger.error(f"메일 상세보기 열기 실패: {e}")
            return None

    async def _extract_detail(self, target_page):
        """상세보기에서 메일 정보 추출 (내부 iframe 포함)"""
        try:
            # 1) 상세 컨테이너 대기(iframe or div)
            # 메시지 본문은 종종 내부 iframe에 들어있음
            inner = None
            for f in await target_page.query_selector_all("iframe"):
                fr = await f.content_frame()
                if fr and await fr.query_selector("#message-container, .mail_content, .message_body, .content"):
                    inner = fr
                    break

            q = lambda sel: (inner or target_page).query_selector(sel)

            # 2) 제목/발신/날짜
            subject = "제목 없음"
            sender = "발신자 불명"
            date = ""
            content = ""

            # 제목 추출
            subject_el = await q("#subjectTitle") or await q(".subject") or await q("h1")
            if subject_el:
                subject = await subject_el.inner_text()

            # 발신자 추출
            sender_el = await q(".sender") or await q(".from") or await q(".name")
            if sender_el:
                sender = await sender_el.inner_text()

            # 날짜 추출
            date_el = await q(".date") or await q(".mail_date") or await q(".timestamp") or await q(".send_date")
            if date_el:
                date = await date_el.inner_text()

            # 3) 본문
            body_el = await (inner or target_page).query_selector("#message-container, #readContentMessageWrap, .mail_content, .message_content, .content, .mail_body, .message_body")
            if body_el:
                content = await body_el.inner_text()

            return subject.strip(), sender.strip(), date.strip(), content.strip()

        except Exception as e:
            logger.error(f"상세 정보 추출 실패: {e}")
            return "제목 없음", "발신자 불명", "", "내용 없음"

    async def _collect_mail_list_new(self, page, process_all, test_mode, processed_mails):
        """새로운 방식: iframe 고정 + 가상 스크롤 + 페이지네이션 + 안전한 처리"""
        mails = []
        total_processed = 0
        max_total_mails = None if not test_mode else 5  # 테스트 모드에서만 5개 제한
        
        try:
            # 1. iframe 고정
            frame = await self._get_mail_frame(page)
            if not frame:
                logger.error("❌ 메일 목록 iframe을 찾을 수 없습니다.")
                return mails
            
            # 2. 페이지네이션 정보 감지
            logger.info("🔍 페이지네이션 정보 감지 시작...")
            current_page, total_pages = await self.pagination_handler.detect_pagination_info(page)
            self.pagination_handler.current_page = current_page
            self.pagination_handler.total_pages = total_pages
            
            logger.info(f"📄 페이지네이션 정보 감지 완료: {current_page}/{total_pages} 페이지")
            
            # 추가 디버깅: 다음 페이지 존재 여부 미리 확인
            has_next_initially = await self.pagination_handler.has_next_page(page)
            logger.info(f"🔄 다음 페이지 존재 여부 초기 확인: {'있음' if has_next_initially else '없음'}")
            
            # 3. 페이지별 처리 루프
            page_count = 0
            while True:
                page_count += 1
                logger.info(f"🔄 페이지 {self.pagination_handler.current_page} 처리 시작...")
                
                # 4. 현재 페이지의 모든 행 미리 로드
                total_rows = await self._load_all_rows(frame)
                if total_rows == 0:
                    logger.warning(f"⚠️ 페이지 {self.pagination_handler.current_page}: 로드된 메일 행이 없습니다.")
                    break
                
                # 5. 메일 행 로케이터 생성
                row_loc = frame.locator("table.mail_list tbody tr[id]:not([id^='dateDesc'])")
                
                # 6. 현재 페이지에서 처리할 메일 수 결정
                current_page_limit = total_rows
                if test_mode and total_processed >= 5:
                    break  # 테스트 모드에서 5개 제한 달성
                elif test_mode:
                    current_page_limit = min(total_rows, 5 - total_processed)
                
                logger.info(f"🚀 페이지 {self.pagination_handler.current_page}: {current_page_limit}개 메일 처리 예정")
                
                # 7. 현재 페이지의 각 메일 행 처리
                page_processed = 0
                for i in range(current_page_limit):
                    try:
                        # 테스트 모드 제한 확인
                        if test_mode and total_processed >= 5:
                            break
                        
                        # 🚀 CRITICAL FIX: Frame 안정성 확인 (Frame was detached 오류 방지)
                        is_stable, current_frame = await self._frame_stability_check(frame)
                        if not is_stable:
                            logger.warning(f"페이지 {self.pagination_handler.current_page} 메일 {i+1}: Frame 불안정, 처리 중단")
                            break
                        
                        row = row_loc.nth(i)
                        mail_id = await row.get_attribute("id")
                        
                        if not mail_id:
                            logger.warning(f"페이지 {self.pagination_handler.current_page} 행 {i+1}: ID 없음 - 스킵")
                            continue
                        
                        # 중복 체크 (테스트 모드에서는 스킵)
                        if not test_mode and processed_mails and mail_id in processed_mails[-200:]:
                            logger.info(f"중복 메일 스킵: {mail_id}")
                            continue
                        
                        logger.info(f"📧 페이지 {self.pagination_handler.current_page} 메일 처리 중 ({i+1}/{current_page_limit}): {mail_id}")
                        
                        # 8. 메일 상세보기 열기
                        mode = await self._open_mail_detail(page, frame, row)
                        if not mode:
                            logger.warning(f"메일 상세보기 열기 실패: {mail_id}")
                            continue
                        
                        # 9. 상세보기에서 정보 추출
                        target_page = page if mode == "same" else page.context.pages[-1]
                        try:
                            subject, sender, date, content = await self._extract_detail(target_page)
                            
                            # 10. 메일 데이터 저장
                            mail_data = {
                                'id': mail_id,
                                'subject': subject,
                                'sender': sender,
                                'date': date,
                                'content': content,
                                'collected_at': datetime.now().isoformat(),
                                'page': self.pagination_handler.current_page
                            }
                            
                            mails.append(mail_data)
                            page_processed += 1
                            total_processed += 1
                            logger.info(f"✅ 메일 수집 성공 (페이지 {self.pagination_handler.current_page}): {subject[:30]}...")
                            
                        finally:
                            # 11. 정리 작업
                            if mode == "popup":
                                await target_page.close()
                            else:
                                await self._return_to_mail_list(page, frame)
                                await self.wait_for_mail_list_loaded(frame, expected_count=1, max_wait=5)
                        
                    except Exception as e:
                        logger.warning(f"페이지 {self.pagination_handler.current_page} 메일 {i+1} 처리 실패: {e}")
                        continue
                
                logger.info(f"📄 페이지 {self.pagination_handler.current_page} 완료: {page_processed}개 처리됨")
                
                # 12. 다음 페이지 확인 및 이동
                if test_mode and total_processed >= 5:
                    logger.info("테스트 모드: 5개 메일 제한 달성, 페이지네이션 중단")
                    break
                
                if not self.pagination_handler.should_continue_pagination(total_processed, max_total_mails):
                    logger.info("페이지네이션 중단 조건 달성")
                    break
                
                # 다음 페이지 존재 여부 확인
                has_next = await self.pagination_handler.has_next_page(page)
                if not has_next:
                    logger.info("마지막 페이지 도달")
                    break
                
                # 다음 페이지로 이동
                logger.info(f"📄 다음 페이지로 이동 중... ({self.pagination_handler.current_page} -> {self.pagination_handler.current_page + 1})")
                next_success = await self.pagination_handler.go_to_next_page(page)
                
                if not next_success:
                    logger.warning("다음 페이지 이동 실패, 페이지네이션 중단")
                    break
                
                # 새 페이지 로딩 대기
                await self.pagination_handler.wait_for_page_load(page)
                
                # iframe 다시 확보 (페이지 이동 후 필요할 수 있음)
                frame = await self._get_mail_frame(page)
                if not frame:
                    logger.error("페이지 이동 후 iframe을 찾을 수 없습니다.")
                    break
            
            logger.info(f"🎉 전체 메일 수집 완료: {total_processed}개 처리됨 ({page_count}페이지)")
            return mails
            
        except Exception as e:
            logger.error(f"메일 목록 수집 실패: {e}")
            return mails
    
    async def _extract_mail_info(self, page, row, mail_id, frame_content=None):
        """개별 메일 정보 추출 (새창 팝업 대응)"""
        try:
            # 메일 클릭하여 상세 보기 - 새창/동일창 감지
            click_result = await self._safe_click_mail_row(page, row, frame_content)
            if not click_result:
                logger.error(f"메일 클릭 실패 (ID: {mail_id})")
                return None
            
            target_page = page  # 기본값
            popup_page = None
            
            if click_result == "popup":
                # 새창 팝업인 경우
                logger.info("새창에서 메일 정보 추출 시도")
                try:
                    # 가장 최근 페이지 (팝업창) 가져오기
                    all_pages = page.context.pages
                    popup_page = all_pages[-1]  # 마지막 페이지가 팝업
                    target_page = popup_page
                    
                    # 팝업 페이지 로딩 대기
                    await popup_page.wait_for_load_state('networkidle', timeout=15000)
                    await asyncio.sleep(3)
                    
                except Exception as popup_e:
                    logger.error(f"팝업 페이지 처리 실패: {popup_e}")
                    return None
            else:
                # 동일 창인 경우
                logger.info("동일 창에서 메일 정보 추출 시도")
                # 페이지 전환 대기
                await asyncio.sleep(5)
            
            # 네트워크 안정화 대기 (페이지 로딩 완료)
            try:
                await page.wait_for_load_state('networkidle', timeout=10000)
                logger.debug("네트워크 안정화 완료")
            except:
                logger.debug("네트워크 안정화 타임아웃 - 계속 진행")
            
            # 메일 상세보기 선택자들 (성공률 높은 순서)
            mail_detail_selectors = [
                '#mailViewContentWrap',              # 가장 일반적
                '#mailViewContent',                  # 콘텐츠 영역
                '.mail_view',                        # 클래스 기반
                '.mail_detail',
                '.message_view',
                '[class*="mail"][class*="view"]',
                '[class*="mail"][class*="detail"]'
            ]
            
            mail_detail_found = False
            
            # 1차: iframe 내부에서 메일 상세보기 검색 (빠른 성공률)
            logger.info("iframe 내부에서 메일 상세보기 검색 중...")
            try:
                iframes = await page.query_selector_all("iframe")
                for iframe_element in iframes:
                    frame_content = await iframe_element.content_frame()
                    if frame_content:
                        for selector in mail_detail_selectors:
                            try:
                                await frame_content.wait_for_selector(selector, timeout=1000)  # 1초만 대기
                                logger.info(f"✅ iframe 내부에서 메일 상세보기 발견: {selector}")
                                mail_detail_found = True
                                break
                            except:
                                continue
                        if mail_detail_found:
                            break
            except Exception as e:
                logger.warning(f"iframe 내부 메일 상세보기 검색 실패: {e}")
            
            # 2차: 메인 페이지에서 메일 상세보기 검색 (iframe 실패시에만)
            if not mail_detail_found:
                logger.info("메인 페이지에서 메일 상세보기 검색 중...")
                for selector in mail_detail_selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=1000)  # 1초만 대기
                        logger.info(f"✅ 메일 상세보기 발견: {selector}")
                        mail_detail_found = True
                        break
                    except:
                        continue
            
            if not mail_detail_found:
                logger.warning(f"메일 상세보기를 찾을 수 없음. 목록에서 기본 정보 추출 시도 (ID: {mail_id})")
                # 메일 상세보기가 로드되지 않은 경우, 메일 목록 행에서 직접 정보 추출
                try:
                    return await self._extract_mail_info_from_list_row(page, row, mail_id, frame_content)
                except Exception as e:
                    logger.error(f"목록에서 메일 정보 추출 실패: {e}")
                    return None
            
            mail_data = {
                'id': mail_id,
                'collected_at': datetime.now().isoformat()
            }
            
            # 제목 추출 - HTML 구조에 맞게 선택자 순서 조정
            subject_selectors = ['#subjectTitle', 'span.subject', '.subject', '.mail_subject', 'h1', 'h2', '.title']
            mail_data['subject'] = await self._extract_text_from_selectors(page, subject_selectors) or '제목 없음'
            
            # 발신자 추출
            sender_selectors = ['.header .name_tag .name', '.sender', '.from', '.mail_from', '.name']
            mail_data['sender'] = await self._extract_text_from_selectors(page, sender_selectors) or '발신자 불명'
            
            # 날짜 추출  
            date_selectors = ['.date', '.mail_date', '.timestamp', '.send_date']
            mail_data['date'] = await self._extract_text_from_selectors(page, date_selectors) or datetime.now().strftime('%Y-%m-%d')
            
            # 본문 추출 (강화된 추출 로직)
            content_text = ""
            try:
                logger.info("📧 메일 본문 추출 시작...")
                
                # 1. 모든 iframe 검색 및 본문 추출
                iframes = await target_page.query_selector_all("iframe")
                logger.info(f"발견된 iframe 수: {len(iframes)}")
                
                for i, iframe_element in enumerate(iframes):
                    try:
                        frame_content = await iframe_element.content_frame()
                        if frame_content:
                            logger.info(f"iframe[{i}] 접근 성공")
                            
                            # iframe 내부에서 본문 선택자들 시도
                            content_selectors = [
                                '#message-container',
                                '#readContentMessageWrap',
                                '#messageContent',
                                '.mail_content',
                                '.message_content',
                                '.content',
                                '.mail_body',
                                '.message_body',
                                'div[class*="content"]',
                                'div[class*="body"]',
                                'div[class*="message"]'
                            ]
                            
                            for selector in content_selectors:
                                try:
                                    content_elem = await frame_content.query_selector(selector)
                                    if content_elem:
                                        iframe_content = await content_elem.inner_text()
                                        if iframe_content and len(iframe_content.strip()) > 20:
                                            content_text = iframe_content.strip()
                                            logger.info(f"✅ iframe[{i}]에서 본문 추출 성공: {len(content_text)}자 (선택자: {selector})")
                                            break
                                except:
                                    continue
                            if content_text:
                                break
                    except Exception as e:
                        logger.debug(f"iframe[{i}] 처리 실패: {e}")
                        continue
                
                # 2. 메인 페이지에서 직접 본문 추출 시도
                if not content_text:
                    logger.info("메인 페이지에서 본문 추출 시도...")
                    content_selectors = [
                        '#readContentMessageWrap', 
                        '#messageContent',
                        '.mail_content', 
                        '.message_content',
                        '.content', 
                        '.mail_body',
                        '.message_body',
                        'div[class*="content"]',
                        'div[class*="body"]',
                        'div[class*="message"]'
                    ]
                    content_text = await self._extract_text_from_selectors(target_page, content_selectors)
                    if content_text:
                        logger.info(f"✅ 메인 페이지에서 본문 추출 성공: {len(content_text)}자")
                
                # 3. 최후 수단: 전체 페이지에서 가장 긴 텍스트 찾기
                if not content_text:
                    logger.info("전체 페이지에서 본문 검색 시도...")
                    all_divs = await target_page.query_selector_all("div")
                    max_length = 0
                    for div in all_divs:
                        try:
                            div_text = await div.inner_text()
                            if div_text and len(div_text.strip()) > max_length and len(div_text.strip()) > 50:
                                # 메뉴나 헤더가 아닌 실제 본문으로 보이는 텍스트
                                if not any(nav_word in div_text.lower() for nav_word in ['menu', '메뉴', 'navigation', '네비게이션', 'header', 'footer']):
                                    max_length = len(div_text.strip())
                                    content_text = div_text.strip()
                        except:
                            continue
                    
                    if content_text:
                        logger.info(f"✅ 전체 페이지 검색에서 본문 추출 성공: {len(content_text)}자")
                    
            except Exception as e:
                logger.warning(f"본문 추출 실패: {e}")
                
            # 본문이 여전히 비어있으면 최소한의 정보라도 저장
            if not content_text or len(content_text.strip()) < 10:
                logger.warning("❌ 본문 추출 실패 - 제목만 사용")
                content_text = f"[본문 추출 실패] 제목: {mail_data.get('subject', 'N/A')}, 발신자: {mail_data.get('sender', 'N/A')}"
            
            mail_data['content'] = content_text
            
            # 첨부파일 정보
            try:
                attachments = []
                attach_selectors = ['.file_wrap .item_file .name', '.attachment .name', '.file_name']
                
                for selector in attach_selectors:
                    try:
                        # 메인 페이지에서 시도
                        attach_items = await page.query_selector_all(selector)
                        if not attach_items:
                            # iframe에서 시도
                            iframes = await page.query_selector_all("iframe")
                            for iframe_element in iframes:
                                frame_content = await iframe_element.content_frame()
                                if frame_content:
                                    attach_items = await frame_content.query_selector_all(selector)
                                    if attach_items:
                                        break
                        
                        for item in attach_items:
                            filename = await item.inner_text()
                            if filename and filename not in attachments:
                                attachments.append(filename)
                                
                        if attachments:
                            break
                    except:
                        continue
                        
                mail_data['attachments'] = attachments
            except:
                mail_data['attachments'] = []
            
            # 목록으로 돌아가기 - 새창/동일창에 따른 처리
            if popup_page:
                # 팝업 창인 경우: 팝업 창 닫기
                logger.info("팝업 창 닫기")
                try:
                    await popup_page.close()
                    logger.info("✅ 팝업 창 닫기 성공")
                except Exception as e:
                    logger.error(f"팝업 창 닫기 실패: {e}")
            else:
                # 동일 창인 경우: 목록 버튼으로 복귀
                logger.info("목록 버튼으로 복귀 시도")
                return_success = await self._return_to_mail_list(target_page, frame_content)
                if not return_success:
                    logger.warning("목록 복귀 실패 - 새 페이지 로드로 복구 시도")
                    try:
                        # 메일 페이지로 다시 이동
                        await page.goto('https://tekville.daouoffice.com/app/mail')
                        await asyncio.sleep(3)
                        # 폴더로 다시 이동
                        await self._navigate_to_folder(page)
                        logger.info("✅ 페이지 복구 완료")
                    except Exception as e:
                        logger.error(f"페이지 복구 실패: {e}")
            
            await asyncio.sleep(1)
            
            return mail_data
            
        except Exception as e:
            logger.error(f"메일 정보 추출 중 오류: {e}")
            return None
    
    async def _extract_text_from_selectors(self, page, selectors):
        """여러 선택자로 텍스트 추출 시도 - iframe detached 오류 방지 강화"""
        for selector in selectors:
            try:
                # 메인 페이지에서 먼저 시도
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if text and text.strip():
                        return text.strip()
                
                # iframe에서 시도 (안정성 강화)
                text = await self._safe_extract_from_iframe(page, selector)
                if text:
                    return text
                        
            except Exception as e:
                logger.debug(f"선택자 '{selector}' 추출 실패: {e}")
                continue
        
        return None
    
    async def _safe_extract_from_iframe(self, page, selector, max_retries=3):
        """iframe에서 안전하게 텍스트 추출 - detached 오류 방지"""
        for retry in range(max_retries):
            try:
                # iframe 목록을 매번 새로 가져오기
                iframes = await page.query_selector_all("iframe")
                logger.debug(f"iframe 추출 시도 {retry + 1}/{max_retries}, 발견된 iframe 수: {len(iframes)}")
                
                for i, iframe_element in enumerate(iframes):
                    try:
                        # iframe이 여전히 유효한지 확인
                        if await self._is_iframe_valid(iframe_element):
                            frame_content = await iframe_element.content_frame()
                            if frame_content:
                                element = await frame_content.query_selector(selector)
                                if element:
                                    text = await element.inner_text()
                                    if text and text.strip():
                                        logger.debug(f"iframe {i}에서 텍스트 추출 성공")
                                        return text.strip()
                    except Exception as e:
                        logger.debug(f"iframe {i} 처리 중 오류: {e}")
                        continue
                
                # 재시도 전 잠시 대기
                if retry < max_retries - 1:
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                logger.debug(f"iframe 추출 재시도 {retry + 1} 실패: {e}")
                if retry < max_retries - 1:
                    await asyncio.sleep(1)
        
        return None
    
    async def _is_iframe_valid(self, iframe_element):
        """iframe이 여전히 유효한지 확인"""
        try:
            # iframe의 기본 속성에 접근해보기
            await iframe_element.get_attribute("name")
            return True
        except Exception:
            return False
    
    async def _return_to_mail_list(self, page, frame_content=None):
        """메일 목록으로 돌아가기 - 목록 버튼 우선 사용"""
        try:
            # 1. 목록 버튼 우선 시도 (더 안정적)
            logger.info("목록 버튼 우선 시도")
            if await self._try_list_button(page):
                logger.info("✅ 목록 버튼으로 복귀 성공")
                
                # 메일 목록이 완전히 로드될 때까지 동적 대기
                if frame_content:
                    list_loaded = await self.wait_for_mail_list_loaded(frame_content, expected_count=80)
                    if not list_loaded:
                        logger.warning("⚠️ 메일 목록 로딩 실패 - 다음 메일 처리 시도")
                    
                    # 선택된 메일 행의 선택 상태 해제
                    try:
                        # 모든 메일 행의 클래스 확인
                        all_rows = await frame_content.query_selector_all("table.mail_list.list_mail001 tbody tr[id*='&']")
                        logger.debug(f"전체 {len(all_rows)}개 행의 클래스 확인 중...")
                        
                        for i, row in enumerate(all_rows[:5]):  # 처음 5개만 확인
                            try:
                                row_class = await row.get_attribute('class')
                                row_id = await row.get_attribute('id')
                                is_visible = await row.is_visible()
                                logger.debug(f"행 {i+1} - ID: {row_id}, 클래스: '{row_class}', 보임: {is_visible}")
                                
                                # 선택된 것으로 보이는 행 찾기 (클래스에 특정 키워드 포함)
                                if row_class and any(keyword in row_class.lower() for keyword in ['select', 'active', 'on', 'current', 'focus', 'highlight']):
                                    logger.debug(f"선택된 행 발견 - {row_id} (클래스: {row_class})")
                                    # 빈 공간 클릭으로 선택 해제 시도
                                    try:
                                        # 메일 목록 테이블의 빈 공간 클릭
                                        table = await frame_content.query_selector("table.mail_list.list_mail001")
                                        if table:
                                            await table.click(position={"x": 10, "y": 10})  # 테이블 왼쪽 상단 클릭
                                            logger.info("✅ 테이블 빈 공간 클릭으로 선택 해제 시도")
                                    except Exception as e:
                                        logger.warning(f"테이블 클릭 실패: {e}")
                                    break
                            except Exception as e:
                                logger.warning(f"행 {i+1} 클래스 확인 실패: {e}")
                                
                    except Exception as e:
                        logger.warning(f"선택된 행 찾기 실패: {e}")
                
                return True
            
            # 2. 목록 버튼 실패시 뒤로가기 시도
            logger.info("목록 버튼 실패, 브라우저 뒤로가기 시도")
            try:
                # 타임아웃을 5초로 더 단축
                await page.go_back(timeout=5000)
                await page.wait_for_timeout(2000)
                
                # 뒤로가기 성공 확인
                if await self._check_mail_list_present(page):
                    logger.info("✅ 뒤로가기로 메일 목록 복귀 성공")
                    return True
            except Exception as e:
                logger.warning(f"뒤로가기도 실패: {e}")
            
            # 3. 모든 방법 실패시 페이지 재로드
            return await self._page_reload_recovery(page)
            
        except Exception as e:
            logger.warning(f"목록으로 돌아가기 실패: {e}")
            return False
    
    async def _try_list_button(self, page):
        """목록 버튼 클릭 시도 (향상된 디버깅과 요소 발견 기능)"""
        
        # 먼저 사용 가능한 모든 요소를 탐색하여 실제 DOM 구조 파악
        await self._discover_available_elements(page)
        
        # 🚀 CRITICAL FIX: 로그 분석 결과 성공률 높은 선택자만 사용 (11개 → 3개)
        priority_selectors = [
            '.ic_toolbar',                    # 로그상 첫 번째로 성공
            'span.ic_toolbar.list',          # 로그상 두 번째로 성공  
            'span[title="목록"]',            # 목록 관련 직접 선택자
        ]
        
        logger.info(f"🚀 최적화된 목록 버튼 찾기 시작 - {len(priority_selectors)}개 우선 선택자 시도")
        
        # 🚀 CRITICAL FIX: 우선순위 선택자로 빠른 시도 (시간 단축)
        for i, selector in enumerate(priority_selectors):
            logger.info(f"[{i+1}/{len(priority_selectors)}] 선택자 시도: {selector}")
            
            try:
                # iframe에서 먼저 시도 (빠른 타임아웃)
                iframes = await page.query_selector_all("iframe")
                logger.debug(f"총 {len(iframes)}개 iframe 발견")
                
                for j, iframe_element in enumerate(iframes):
                    try:
                        logger.debug(f"  iframe [{j+1}] 검사 중...")
                        if await self._is_iframe_valid(iframe_element):
                            frame_content = await iframe_element.content_frame()
                            if frame_content:
                                # 빠른 요소 검색 (1초 타임아웃)
                                try:
                                    element = await frame_content.wait_for_selector(selector, timeout=1000)
                                    if element:
                                        # 요소가 실제로 클릭 가능한지 확인
                                        is_visible = await element.is_visible()
                                        is_enabled = await element.is_enabled()
                                        logger.info(f"  ✅ iframe[{j+1}]에서 요소 발견: {selector} (visible: {is_visible}, enabled: {is_enabled})")
                                        
                                        if is_visible and is_enabled:
                                            # 🚀 CRITICAL FIX: popOverlay 오버레이 제거 후 클릭
                                            try:
                                                # 먼저 오버레이 제거 시도
                                                await page.evaluate("() => { const overlay = document.getElementById('popOverlay'); if (overlay) overlay.remove(); }")
                                                await page.wait_for_timeout(100)  # 오버레이 제거 대기
                                                
                                                # Force 클릭으로 오버레이 무시
                                                await element.click(force=True, timeout=3000)
                                                logger.info(f"✅ iframe[{j+1}]에서 목록 버튼 클릭 성공: {selector} (오버레이 우회)")
                                            except Exception as click_error:
                                                # Force 클릭도 실패하면 JavaScript 클릭 시도
                                                logger.warning(f"Force 클릭 실패: {click_error}, JavaScript 클릭 시도")
                                                await element.evaluate("el => el.click()")
                                                logger.info(f"✅ iframe[{j+1}]에서 JavaScript 클릭 성공: {selector}")
                                            
                                            await page.wait_for_timeout(1000)  # 2초→1초로 단축
                                            if await self._check_mail_list_present(page):
                                                logger.info(f"✅ 목록 버튼으로 복귀 성공")
                                                return True
                                            else:
                                                logger.debug(f"목록 복귀 확인 실패, 클릭은 성공했지만 목록이 보이지 않음")
                                                # 클릭은 성공했으므로 일단 성공으로 처리 (목록 확인 로직이 너무 엄격할 수 있음)
                                                return True
                                        else:
                                            logger.debug(f"  요소를 찾았지만 클릭할 수 없음: visible={is_visible}, enabled={is_enabled}")
                                except Exception as e:
                                    # 🚨 진단: 실제 클릭 실패 원인 로깅 추가
                                    logger.warning(f"iframe[{j+1}] {selector} 클릭 실패: {e}")
                                    continue
                    except Exception as iframe_e:
                        logger.debug(f"  iframe[{j+1}] 목록 버튼 시도 실패: {iframe_e}")
                        continue
                
                # 메인 페이지에서 시도 (빠른 타임아웃)
                logger.debug("메인 페이지에서 검사 중...")
                try:
                    element = await page.wait_for_selector(selector, timeout=1000)  # 1초 타임아웃
                    if element:
                        is_visible = await element.is_visible()
                        is_enabled = await element.is_enabled()
                        logger.info(f"✅ 메인 페이지에서 요소 발견: {selector} (visible: {is_visible}, enabled: {is_enabled})")
                        
                        if is_visible and is_enabled:
                            # 🚀 CRITICAL FIX: popOverlay 오버레이 제거 후 클릭 (메인 페이지)
                            try:
                                # 먼저 오버레이 제거 시도
                                await page.evaluate("() => { const overlay = document.getElementById('popOverlay'); if (overlay) overlay.remove(); }")
                                await page.wait_for_timeout(100)  # 오버레이 제거 대기
                                
                                # Force 클릭으로 오버레이 무시
                                await element.click(force=True, timeout=3000)
                                logger.info(f"✅ 메인 페이지에서 목록 버튼 클릭 성공: {selector} (오버레이 우회)")
                            except Exception as click_error:
                                # Force 클릭도 실패하면 JavaScript 클릭 시도
                                logger.warning(f"메인 페이지 Force 클릭 실패: {click_error}, JavaScript 클릭 시도")
                                await element.evaluate("el => el.click()")
                                logger.info(f"✅ 메인 페이지에서 JavaScript 클릭 성공: {selector}")
                            
                            await page.wait_for_timeout(1000)  # 2초→1초로 단축
                            if await self._check_mail_list_present(page):
                                logger.info(f"✅ 목록 버튼으로 복귀 성공")
                                return True
                            else:
                                logger.debug(f"목록 복귀 확인 실패, 클릭은 성공했지만 목록이 보이지 않음")
                                # 클릭은 성공했으므로 일단 성공으로 처리
                                return True
                        else:
                            logger.debug(f"메인 페이지 요소를 찾았지만 클릭할 수 없음: visible={is_visible}, enabled={is_enabled}")
                except Exception as e:
                    # 🚨 진단: 메인 페이지 클릭 실패 원인 로깅 추가
                    logger.warning(f"메인 페이지 {selector} 클릭 실패: {e}")
                    continue
                        
            except Exception as e:
                logger.debug(f"선택자 {selector} 시도 중 오류: {e}")
                continue
        
        logger.error("모든 선택자로 목록 버튼을 찾지 못함")
        return False
    
    async def _discover_available_elements(self, page):
        """현재 페이지와 iframe에서 사용 가능한 요소들을 탐색"""
        logger.debug("🔍 DOM 요소 탐색 시작...")
        
        try:
            # iframe 탐색
            iframes = await page.query_selector_all("iframe")
            for i, iframe_element in enumerate(iframes):
                try:
                    if await self._is_iframe_valid(iframe_element):
                        frame_content = await iframe_element.content_frame()
                        if frame_content:
                            logger.info(f"📋 iframe[{i+1}] DOM 구조 탐색:")
                            
                            # toolbar 관련 요소들 찾기
                            toolbar_elements = await frame_content.query_selector_all('*[class*="toolbar"], *[class*="ic_"], span, button')
                            logger.info(f"  - toolbar/span/button 요소: {len(toolbar_elements)}개 발견")
                            
                            for j, elem in enumerate(toolbar_elements[:10]):  # 최대 10개만 출력
                                try:
                                    tag_name = await elem.evaluate('element => element.tagName')
                                    class_name = await elem.evaluate('element => element.className || ""')
                                    title = await elem.evaluate('element => element.title || ""')
                                    onclick = await elem.evaluate('element => element.onclick ? element.onclick.toString() : ""')
                                    text_content = await elem.evaluate('element => element.textContent?.trim() || ""')
                                    
                                    logger.info(f"    [{j+1}] {tag_name} class='{class_name}' title='{title}' text='{text_content[:30]}'")
                                    if onclick:
                                        logger.info(f"        onclick: {onclick[:100]}...")
                                except:
                                    continue
                            
                            # title="목록" 또는 유사한 속성을 가진 요소들 찾기  
                            list_related = await frame_content.query_selector_all('*[title*="목록"], *[class*="list"], *[onclick*="list"]')
                            if list_related:
                                logger.info(f"  📌 목록 관련 요소: {len(list_related)}개 발견")
                                for k, elem in enumerate(list_related[:5]):
                                    try:
                                        tag_name = await elem.evaluate('element => element.tagName')
                                        class_name = await elem.evaluate('element => element.className || ""')
                                        title = await elem.evaluate('element => element.title || ""')
                                        logger.info(f"    [목록{k+1}] {tag_name} class='{class_name}' title='{title}'")
                                    except:
                                        continue
                            
                except Exception as e:
                    logger.debug(f"iframe[{i+1}] 탐색 실패: {e}")
                    continue
            
            # 메인 페이지도 탐색
            logger.info("📋 메인 페이지 DOM 구조 탐색:")
            main_toolbar = await page.query_selector_all('*[class*="toolbar"], *[class*="ic_"], span, button')
            logger.info(f"  - toolbar/span/button 요소: {len(main_toolbar)}개 발견")
            
            for j, elem in enumerate(main_toolbar[:5]):  # 최대 5개만 출력
                try:
                    tag_name = await elem.evaluate('element => element.tagName')
                    class_name = await elem.evaluate('element => element.className || ""')
                    title = await elem.evaluate('element => element.title || ""')
                    text_content = await elem.evaluate('element => element.textContent?.trim() || ""')
                    
                    logger.info(f"  [메인{j+1}] {tag_name} class='{class_name}' title='{title}' text='{text_content[:30]}'")
                except:
                    continue
            
            logger.debug("🔍 DOM 요소 탐색 완료")
            
        except Exception as e:
            logger.warning(f"DOM 요소 탐색 중 오류: {e}")
    
    async def _check_mail_list_present(self, page):
        """메일 목록이 있는지 확인 (더 관대한 조건)"""
        try:
            # 짧은 대기 후 확인 (페이지 전환 시간 고려)
            await page.wait_for_timeout(500)
            
            # 다양한 선택자로 메일 목록 확인
            mail_list_selectors = [
                ".mail_list", 
                "table.mail_list", 
                ".mail_list_wrap",
                "table.list_mail001",
                "#mail_list_content"
            ]
            
            # iframe 내부에서 메일 목록 확인
            iframes = await page.query_selector_all("iframe")
            for iframe_element in iframes:
                try:
                    if await self._is_iframe_valid(iframe_element):
                        frame = await iframe_element.content_frame()
                        if frame:
                            for selector in mail_list_selectors:
                                try:
                                    mail_list = await frame.query_selector(selector)
                                    if mail_list and await mail_list.is_visible():
                                        logger.debug(f"목록 복귀 확인: iframe에서 {selector} 발견")
                                        return True
                                except:
                                    continue
                except:
                    continue
            
            # 메인 페이지에서도 확인
            for selector in mail_list_selectors:
                try:
                    mail_list = await page.query_selector(selector)
                    if mail_list and await mail_list.is_visible():
                        logger.debug(f"목록 복귀 확인: 메인에서 {selector} 발견")
                        return True
                except:
                    continue
            
            logger.debug("목록 복귀 확인 실패 - 메일 목록을 찾을 수 없음")
            return False
            
        except Exception as e:
            logger.debug(f"목록 복귀 확인 중 오류: {e}")
            return False
    
    async def _frame_stability_check(self, frame):
        """Frame 안정성 확인 및 복구 - 🚀 CRITICAL FIX: Frame detached 오류 방지"""
        try:
            # Frame이 여전히 활성 상태인지 확인
            await frame.locator('body').count()
            return True, frame
        except Exception as e:
            if "detached" in str(e).lower():
                logger.warning("⚠️ Frame이 분리됨, 재연결 필요")
                return False, None
            return True, frame

    async def _page_reload_recovery(self, page):
        """페이지 재로드로 복구"""
        logger.warning("모든 방법 실패, 페이지 재로드로 복구 시도")
        try:
            # 브라우저가 살아있는지 확인
            if page.is_closed():
                logger.error("브라우저가 이미 종료됨 - 복구 불가")
                return False
                
            # 메일 페이지로 다시 이동
            await page.goto('https://tekville.daouoffice.com/app/mail', timeout=15000)
            await page.wait_for_timeout(3000)
            
            # 폴더로 다시 이동
            success = await self._navigate_to_folder(page)
            if success:
                logger.info("✅ 페이지 재로드로 목록 복구 성공")
                return True
            else:
                logger.error("페이지 재로드 후 폴더 이동 실패")
                return False
                
        except Exception as e:
            logger.error(f"페이지 재로드 복구 실패: {e}")
            return False
    
    
    async def _extract_mail_info_from_list_row_safe(self, page, row, mail_id, frame_content=None):
        """메일 목록에서 안전하게 기본 정보 추출 (fallback용) - 향상된 버전"""
        try:
            logger.info(f"목록에서 기본 정보 추출 시도: {mail_id}")
            
            # DOM 존재 여부 확인 (CSS 가시성 무시)
            try:
                row_id = await row.get_attribute('id')
                if not row_id:
                    logger.warning(f"Row element has no ID: {mail_id}")
                    return None
            except Exception as e:
                logger.warning(f"Row element access failed: {mail_id} - {e}")
                return None
            
            # 행에서 가져올 수 있는 기본 정보들
            mail_data = {
                'id': mail_id,
                'subject': '제목 없음',
                'sender': '발신자 불명',
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'content': '내용을 확인할 수 없습니다 (목록에서 추출)',
                'read_status': 'unknown',
                'attachments': [],
                'collected_at': datetime.now().isoformat()
            }
            
            # 행에서 텍스트 정보들 추출 시도 (여러 방법으로)
            try:
                # 방법 1: 모든 td 셀 분석
                tds = await row.query_selector_all('td')
                logger.debug(f"발견된 td 셀 수: {len(tds)}")
                
                if tds and len(tds) >= 2:
                    # 각 셀의 내용을 분석하여 제목, 발신자, 날짜 추출
                    cell_texts = []
                    for i, td in enumerate(tds):
                        try:
                            td_text = await td.inner_text()
                            td_class = await td.get_attribute('class') or ''
                            cell_texts.append({
                                'index': i,
                                'text': td_text.strip() if td_text else '',
                                'class': td_class,
                                'length': len(td_text.strip()) if td_text else 0
                            })
                        except:
                            cell_texts.append({'index': i, 'text': '', 'class': '', 'length': 0})
                    
                    # 제목 찾기 (가장 긴 텍스트이거나 subject 클래스)
                    subject_found = False
                    for cell in cell_texts:
                        if 'subject' in cell['class'].lower() and cell['length'] > 3:
                            mail_data['subject'] = cell['text'][:100]
                            subject_found = True
                            logger.debug(f"클래스 기반 제목 발견: {mail_data['subject'][:30]}...")
                            break
                    
                    if not subject_found:
                        # 클래스로 못 찾으면 가장 긴 텍스트를 제목으로 (단, 의미있는 텍스트)
                        meaningful_cells = [
                            cell for cell in cell_texts 
                            if cell['length'] > 5 and not cell['text'].isdigit() 
                            and not any(pattern in cell['text'] for pattern in [':', 'AM', 'PM', '/', '@'])
                        ]
                        if meaningful_cells:
                            longest_cell = max(meaningful_cells, key=lambda x: x['length'])
                            mail_data['subject'] = longest_cell['text'][:100]
                            logger.debug(f"길이 기반 제목 발견: {mail_data['subject'][:30]}...")
                    
                    # 발신자 찾기 (from 클래스이거나 @ 포함)
                    sender_found = False
                    for cell in cell_texts:
                        if any(keyword in cell['class'].lower() for keyword in ['from', 'sender']) and cell['length'] > 0:
                            mail_data['sender'] = cell['text'][:50]
                            sender_found = True
                            logger.debug(f"클래스 기반 발신자 발견: {mail_data['sender']}")
                            break
                        elif '@' in cell['text'] and cell['length'] > 3:
                            mail_data['sender'] = cell['text'][:50]
                            sender_found = True
                            logger.debug(f"이메일 패턴 발신자 발견: {mail_data['sender']}")
                            break
                    
                    if not sender_found and len(cell_texts) > 1:
                        # 두 번째 셀을 발신자로 추정 (일반적인 패턴)
                        if cell_texts[1]['length'] > 0:
                            mail_data['sender'] = cell_texts[1]['text'][:50]
                            logger.debug(f"위치 기반 발신자 추정: {mail_data['sender']}")
                    
                    # 날짜 찾기 (date 클래스이거나 날짜 패턴)
                    date_found = False
                    for cell in cell_texts:
                        if any(keyword in cell['class'].lower() for keyword in ['date', 'time']) and cell['length'] > 0:
                            mail_data['date'] = cell['text']
                            date_found = True
                            logger.debug(f"클래스 기반 날짜 발견: {mail_data['date']}")
                            break
                        elif any(pattern in cell['text'] for pattern in [':', '-', '오늘', '어제', '/']):
                            mail_data['date'] = cell['text']
                            date_found = True
                            logger.debug(f"패턴 기반 날짜 발견: {mail_data['date']}")
                            break
                    
                    if not date_found and len(cell_texts) > 0:
                        # 마지막 셀을 날짜로 추정
                        last_cell = cell_texts[-1]
                        if last_cell['length'] > 0:
                            mail_data['date'] = last_cell['text']
                            logger.debug(f"위치 기반 날짜 추정: {mail_data['date']}")
                
                # 방법 2: 전체 행 텍스트에서 추출 (위 방법이 실패한 경우)
                if mail_data['subject'] == '제목 없음':
                    row_text = await row.inner_text()
                    if row_text and row_text.strip():
                        lines = [line.strip() for line in row_text.split('\n') if line.strip()]
                        if lines:
                            # 가장 긴 줄을 제목으로 사용
                            longest_line = max(lines, key=len)
                            if len(longest_line) > 5:
                                mail_data['subject'] = longest_line[:100]
                                logger.debug(f"전체 텍스트에서 제목 추출: {mail_data['subject'][:30]}...")
                
            except Exception as extract_e:
                logger.debug(f"목록 정보 추출 중 오류: {extract_e}")
            
            logger.info(f"목록에서 추출된 정보: 제목={mail_data['subject'][:30]}..., 발신자={mail_data['sender']}")
            return mail_data
            
        except Exception as e:
            logger.error(f"목록에서 안전한 정보 추출 실패: {e}")
            return None
    
    async def _safe_click_mail_row(self, page, row, frame_content=None):
        """메일 제목을 클릭하여 내용 페이지로 이동 (안정성 개선)"""
        try:
            # DOM 존재 여부 확인
            try:
                row_id = await row.get_attribute('id')
                if not row_id:
                    logger.warning("메일 행 ID 없음 - 스킵")
                    return False
            except Exception as e:
                logger.warning(f"행 접근 실패: {e}")
                return False
            
            # 현재 페이지 수 기록 (새창 감지를 위해)
            initial_pages = len(page.context.pages)
            
            # 1. 제목 셀 찾아서 클릭 (실제 HTML 구조 기반으로 수정)
            title_selectors = [
                'td.subject.mailPadding',              # 실제 제목 셀 구조
                'td.subject.mailPadding span.subject', # 제목 스팬
                'td.subject a',                        # 제목 링크
                'td.subject',                          # 제목 셀 
                '.subject a',                          # 일반적인 제목 링크
                '.subject',                            # 일반적인 제목 셀
                'a[href*="mail"]',                     # 메일 링크
                'td:nth-child(3)',                     # 실제로는 3번째가 제목 (체크박스, 발신자, 제목 순)
                'td:nth-child(2) a',                   # 두 번째 td의 링크
                'td:nth-child(3) a'                    # 세 번째 td의 링크
            ]
            
            for selector in title_selectors:
                try:
                    title_element = await row.query_selector(selector)
                    if title_element:
                        # CSS 가시성 무시하고 강제 클릭
                        try:
                            await title_element.click(force=True, timeout=3000)  # 타임아웃 명시
                            logger.info(f"제목 링크 클릭 성공: {selector}")
                            
                            # 새창 팝업 감지 (1초로 단축)
                            await page.wait_for_timeout(1000)  # 2초→1초
                            new_pages = len(page.context.pages)
                            
                            if new_pages > initial_pages:
                                logger.info("새창 팝업 감지됨")
                                return "popup"
                            else:
                                logger.info("동일 창에서 메일 내용 로드됨")
                                return "same_page"
                        except Exception as click_e:
                            logger.debug(f"제목 요소 클릭 실패: {click_e}")
                            continue
                            
                except Exception as e:
                    logger.debug(f"제목 클릭 실패 ({selector}): {e}")
                    continue
            
            # 2. 제목 클릭이 실패하면 행 전체 클릭 (타임아웃 단축)
            logger.info("제목 클릭 실패, 행 전체 클릭 시도")
            try:
                # DOM 존재 여부 확인
                try:
                    row_id = await row.get_attribute('id')
                    if not row_id:
                        logger.warning("행 ID를 찾을 수 없음")
                        return False
                except Exception as e:
                    logger.warning(f"행 접근 실패: {e}")
                    return False
                await row.click(force=True, timeout=3000)  # 강제 클릭
                logger.info("행 전체 클릭 성공")
                
                # 새창 팝업 감지 (1초로 단축)
                await page.wait_for_timeout(1000)  # 2초→1초
                new_pages = len(page.context.pages)
                
                if new_pages > initial_pages:
                    logger.info("새창 팝업 감지됨")
                    return "popup"
                else:
                    logger.info("동일 창에서 메일 내용 로드됨")
                    return "same_page"
                    
            except Exception as e:
                logger.warning(f"행 전체 클릭 실패: {e}")
            
            # 3. 강제 클릭 시도 (최후의 수단)
            try:
                await row.click(force=True, timeout=2000)  # 타임아웃 명시
                logger.info("강제 클릭 성공")
                await page.wait_for_timeout(1000)  # 2초→1초
                return "same_page"
            except Exception as e:
                logger.warning(f"강제 클릭 실패: {e}")
                
            logger.error("모든 클릭 방법이 실패했습니다")
            return False
            
        except Exception as e:
            logger.error(f"메일 클릭 중 치명적 오류: {e}")
            return False
    
    async def _extract_mail_info_from_list_row(self, page, row, mail_id, frame_content=None):
        """메일 목록 행에서 직접 정보 추출 (상세보기 로드 실패 시 대안)"""
        try:
            logger.info(f"메일 목록 행에서 정보 추출 시작 (ID: {mail_id})")
            
            mail_data = {
                'id': mail_id,
                'collected_at': datetime.now().isoformat()
            }
            
            # 행에서 직접 정보 추출 시도
            try:
                # 모든 td 요소 확인
                all_tds = await row.query_selector_all('td')
                logger.info(f"행에서 발견된 td 요소 수: {len(all_tds)}")
                
                # 제목 - HTML 구조 분석 결과에 따라 정확한 위치 찾기
                # 실제 HTML 구조에 따라 제목 셀 찾기
                subject_cell = await row.query_selector('td.subject.mailPadding')  # 실제 구조
                if not subject_cell:
                    subject_cell = await row.query_selector('td.subject')
                if not subject_cell and len(all_tds) > 0:
                    # td 순서별로 확인 (실제 구조: 체크박스, 발신자, 제목, 날짜, 크기 순)
                    for i, td in enumerate(all_tds):
                        td_class = await td.get_attribute('class') or ''
                        if 'subject' in td_class.lower():
                            subject_cell = td
                            logger.info(f"제목 셀 발견: td[{i}], class='{td_class}'")
                            break
                    
                    # 클래스로 찾지 못하면 위치 기반 (실제로는 2번째가 제목)
                    if not subject_cell and len(all_tds) >= 3:
                        subject_cell = all_tds[2]  # 실제 구조에서는 3번째가 제목 (인덱스 2)
                        logger.info(f"위치 기반으로 제목 셀 추정: td[2] (실제 구조 기반)")
                
                if subject_cell:
                    # subject 셀 내부 구조 확인
                    try:
                        # span.subject 찾기
                        subject_span = await subject_cell.query_selector('span.subject')
                        if subject_span:
                            subject_text = await subject_span.inner_text()
                            logger.info(f"span.subject에서 제목 추출: {subject_text[:50]}...")
                        else:
                            # span.subject가 없으면 전체 td 내용
                            subject_text = await subject_cell.inner_text()
                            logger.info(f"td 전체에서 제목 추출: {subject_text[:50]}...")
                        
                        # 빈 제목 처리
                        if subject_text and subject_text.strip():
                            mail_data['subject'] = subject_text.strip()[:100]
                        else:
                            mail_data['subject'] = '제목 없음'
                    except Exception as subject_e:
                        logger.warning(f"제목 추출 중 오류: {subject_e}")
                        mail_data['subject'] = '제목 추출 실패'
                else:
                    logger.warning("제목 셀을 찾을 수 없음")
                    mail_data['subject'] = '제목 없음'
                
                # 발신자 - HTML 구조에 따라 올바른 위치 찾기
                sender_cell = None
                if len(all_tds) > 1:
                    # 발신자는 보통 2-3번째 위치
                    for i in range(1, min(len(all_tds), 4)):
                        td_class = await all_tds[i].get_attribute('class') or ''
                        if any(keyword in td_class.lower() for keyword in ['from', 'sender']):
                            sender_cell = all_tds[i]
                            logger.info(f"발신자 셀 발견: td[{i}], class='{td_class}'")
                            break
                    
                    # 클래스로 찾지 못하면 추정 (체크박스 다음)
                    if not sender_cell and len(all_tds) >= 2:
                        sender_cell = all_tds[1]  # 보통 2번째가 발신자
                        logger.info(f"위치 기반으로 발신자 셀 추정: td[1]")
                
                if sender_cell:
                    sender_text = await sender_cell.inner_text()
                    mail_data['sender'] = sender_text.strip()[:50] if sender_text and sender_text.strip() else '발신자 불명'
                else:
                    mail_data['sender'] = '발신자 불명'
                
                # 날짜 - 실제 HTML 구조에 따라 찾기 (td.redate.mailPadding)
                date_cell = await row.query_selector('td.redate.mailPadding')  # 실제 구조
                if not date_cell and len(all_tds) > 0:
                    # 클래스 기반으로 찾기
                    for i in range(len(all_tds)):
                        td_class = await all_tds[i].get_attribute('class') or ''
                        td_text = await all_tds[i].inner_text()
                        # 날짜 관련 클래스나 패턴 확인
                        if any(keyword in td_class.lower() for keyword in ['date', 'redate', 'time']) or \
                           any(pattern in td_text for pattern in [':', '-', '오늘', '어제', 'AM', 'PM']):
                            date_cell = all_tds[i]
                            logger.info(f"날짜 셀 발견: td[{i}], class='{td_class}', text='{td_text[:20]}...'")
                            break
                    
                    # 패턴으로 찾지 못하면 마지막에서 두 번째 셀 (크기 셀 전)
                    if not date_cell and len(all_tds) >= 2:
                        date_cell = all_tds[-2]  # 실제 구조에서는 마지막에서 두 번째가 날짜
                        logger.info(f"위치 기반으로 날짜 셀 추정: td[{len(all_tds)-2}] (실제 구조 기반)")
                
                if date_cell:
                    date_text = await date_cell.inner_text()
                    mail_data['date'] = date_text.strip() if date_text and date_text.strip() else datetime.now().strftime('%Y-%m-%d')
                else:
                    mail_data['date'] = datetime.now().strftime('%Y-%m-%d')
                
                # 본문은 목록에서 추출하기 어려우므로 기본값 (URL 포함 가능한 형태로 개선)
                mail_data['content'] = f"[메일 목록에서 추출] 제목: {mail_data.get('subject', 'N/A')}, 발신자: {mail_data.get('sender', 'N/A')}, 날짜: {mail_data.get('date', 'N/A')} - 상세 내용은 메일 상세보기에서 확인하세요."
                mail_data['attachments'] = []
                
                logger.info(f"목록에서 추출된 정보: 제목={mail_data['subject'][:30]}..., 발신자={mail_data['sender']}")
                return mail_data
                
            except Exception as e:
                logger.error(f"목록 행에서 정보 추출 실패: {e}")
                
                # 최소한의 정보라도 제공
                mail_data.update({
                    'subject': '정보 추출 실패',
                    'sender': '알 수 없음',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'content': '메일 정보를 추출할 수 없습니다',
                    'attachments': []
                })
                return mail_data
                
        except Exception as e:
            logger.error(f"목록 행에서 메일 정보 추출 중 오류: {e}")
            return None
    
    async def _extract_mail_info_from_list_row_safe(self, page, row, mail_id, frame_content=None):
        """안전한 목록 행에서 메일 정보 추출"""
        try:
            # DOM 존재 여부 확인 (CSS 가시성 무시)
            try:
                row_id = await row.get_attribute('id')
                if not row_id:
                    logger.warning(f"Row element has no ID: {mail_id}")
                    return None
            except Exception as e:
                logger.warning(f"Row element access failed: {mail_id} - {e}")
                return None
            
            return await self._extract_mail_info_from_list_row(page, row, mail_id, frame_content)
        except Exception as e:
            if "detached" in str(e).lower():
                logger.warning(f"List row extraction - Element detached: {mail_id}")
            else:
                logger.warning(f"List row extraction error: {e}")
            return None