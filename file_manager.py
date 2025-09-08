import os
import json
import logging
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from dynamic_category_manager import DynamicCategoryManager

logger = logging.getLogger(__name__)

class EnhancedFileManager:
    def __init__(self, base_path: str, file_format: str = ".md"):
        """향상된 파일 관리자 초기화"""
        self.base_path = Path(base_path)
        self.file_format = file_format
        
        # 디렉토리 구조 정의 (필요할 때만 생성)
        self.topics_dir = self.base_path / "Topics"
        self.daily_dir = self.base_path / "DailyEmails"
        
        # 중복 방지용 인덱스 파일
        self.processed_index_file = self.base_path / "processed_index.json"
        self.processed_index = self._load_processed_index()
        
        # 동적 카테고리 관리자
        self.category_manager = DynamicCategoryManager(str(self.base_path))
        
        logger.info(f"향상된 파일 관리자 초기화 완료: {self.base_path}")
    
    def _load_processed_index(self) -> Dict:
        """처리된 메일 인덱스 로드"""
        try:
            if self.processed_index_file.exists():
                with open(self.processed_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"처리된 메일 인덱스 로드 실패: {e}")
            return {}
    
    def _save_processed_index(self):
        """처리된 메일 인덱스 저장"""
        try:
            with open(self.processed_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.processed_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"처리된 메일 인덱스 저장 실패: {e}")
    
    def _calculate_content_checksum(self, mail_data: Dict) -> str:
        """메일 내용 체크섬 계산"""
        content = f"{mail_data.get('subject', '')}{mail_data.get('date', '')}{mail_data.get('sender', '')}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]
    
    def is_already_processed(self, mail_id: str, mail_data: Dict) -> bool:
        """메일이 이미 처리되었는지 확인 (ID + 내용 체크섬 이중 검증)"""
        if mail_id not in self.processed_index:
            return False
        
        # 내용 체크섬 확인으로 이중 검증
        current_checksum = self._calculate_content_checksum(mail_data)
        stored_checksum = self.processed_index[mail_id].get('checksum', '')
        
        if current_checksum != stored_checksum:
            logger.warning(f"메일 ID는 동일하지만 내용이 다름: {mail_id}")
            return False
        
        logger.debug(f"이미 처리된 메일: {mail_id} ({self.processed_index[mail_id]['date']})")
        return True
    
    def save_mail_enhanced(self, mail_data: Dict, classification: Dict, mail_id: str) -> Dict:
        """향상된 메일 저장 (주제별 + 날짜별)"""
        try:
            # 중복 확인
            if self.is_already_processed(mail_id, mail_data):
                return {
                    "status": "skipped", 
                    "reason": "already_processed",
                    "mail_id": mail_id
                }
            
            # 동적 카테고리 추천 받기
            recommendation = self.category_manager.get_category_recommendation(mail_data)
            final_category = recommendation["suggested_category"]
            
            # 사용자 분류가 있으면 우선 사용
            if classification.get('category') and classification['category'] != '기타':
                final_category = classification['category']
            
            # 카테고리 통계 업데이트
            self.category_manager.update_category_stats(final_category, mail_data)
            
            # 실제로 파일을 저장할 때만 폴더 생성
            self.topics_dir.mkdir(parents=True, exist_ok=True)
            self.daily_dir.mkdir(parents=True, exist_ok=True)
            
            current_time = datetime.now()
            date_str = current_time.strftime("%Y-%m-%d")
            time_str = current_time.strftime("%H:%M")
            
            result = {
                "status": "success",
                "mail_id": mail_id,
                "category": final_category,
                "files_created": [],
                "recommendation": recommendation
            }
            
            # 1. 주제별 파일에 저장 (최신 내용 위로)
            topic_file_path = self._save_to_topic_file(
                final_category, mail_data, classification, date_str, time_str
            )
            result["files_created"].append(str(topic_file_path))
            
            # 2. 날짜별 파일에 저장
            daily_file_path = self._save_to_daily_file(
                mail_data, classification, final_category, date_str, time_str
            )
            result["files_created"].append(str(daily_file_path))
            
            # 3. 처리된 메일 인덱스에 추가
            self._add_to_processed_index(mail_id, mail_data, final_category)
            
            # 4. 카테고리 재편 필요성 확인 (100개마다)
            total_processed = len(self.processed_index)
            if total_processed > 0 and total_processed % 100 == 0:
                result["reorganization_check"] = self._check_reorganization_needs()
            
            logger.info(f"메일 저장 완료: {mail_id} → {final_category}")
            return result
            
        except Exception as e:
            logger.error(f"메일 저장 실패: {e}")
            return {
                "status": "error",
                "mail_id": mail_id,
                "error": str(e)
            }
    
    def _save_to_topic_file(self, category: str, mail_data: Dict, classification: Dict, 
                           date_str: str, time_str: str) -> Path:
        """주제별 파일에 저장 (최신 내용 위로)"""
        filename = f"{self._sanitize_filename(category)}{self.file_format}"
        filepath = self.topics_dir / filename
        
        # 새 메일 내용 생성
        new_content = self._create_topic_entry(mail_data, classification, date_str, time_str)
        
        if filepath.exists():
            # 기존 파일에 최신 내용을 위에 추가
            with open(filepath, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            
            # 헤더와 본문 분리
            lines = existing_content.split('\n')
            header_end = 0
            for i, line in enumerate(lines):
                if line.strip() == "---" and i > 3:  # 첫 번째 구분선 찾기
                    header_end = i + 1
                    break
            
            if header_end > 0:
                header = '\n'.join(lines[:header_end])
                body = '\n'.join(lines[header_end:])
                content = header + '\n' + new_content + '\n' + body
            else:
                content = new_content + '\n\n' + existing_content
        else:
            # 새 파일 생성
            header = f"# {category}\n\n생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
            content = header + new_content
        
        # 파일 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
    
    def _save_to_daily_file(self, mail_data: Dict, classification: Dict, category: str,
                           date_str: str, time_str: str) -> Path:
        """날짜별 파일에 주제별로 정리해서 저장 (통계 없이)"""
        filename = f"{date_str}{self.file_format}"
        filepath = self.daily_dir / filename
        
        # 새 메일 엔트리 생성
        new_entry = f"### {time_str} - {mail_data.get('subject', '제목 없음')}\n"
        new_entry += f"**요약**: {classification.get('summary', '요약 없음')}\n\n"
        
        if classification.get('action_required'):
            new_entry += "⚠️ **조치 필요**\n\n"
        
        new_entry += "---\n\n"
        
        if filepath.exists():
            # 기존 파일 읽기
            with open(filepath, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            
            # 해당 카테고리 섹션 찾아서 추가
            content = self._add_to_category_section(existing_content, category, new_entry, date_str)
        else:
            # 새 파일 생성
            header = f"# {date_str} 메일 요약\n\n"
            content = header + f"## 📧 {category}\n\n" + new_entry
        
        # 파일 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
    
    def _add_to_category_section(self, existing_content: str, category: str, new_entry: str, date_str: str) -> str:
        """기존 내용에서 해당 카테고리 섹션을 찾아서 새 엔트리 추가"""
        lines = existing_content.split('\n')
        category_section = f"## 📧 {category}"
        
        # 카테고리 섹션이 있는지 찾기
        category_index = -1
        for i, line in enumerate(lines):
            if line == category_section:
                category_index = i
                break
        
        if category_index >= 0:
            # 기존 카테고리 섹션에 추가 (섹션 바로 다음에)
            next_section_index = len(lines)
            for i in range(category_index + 1, len(lines)):
                if lines[i].startswith("## 📧"):
                    next_section_index = i
                    break
            
            # 새 엔트리를 카테고리 섹션 끝에 추가
            lines.insert(next_section_index, new_entry.rstrip())
            return '\n'.join(lines)
        else:
            # 새 카테고리 섹션 생성 (맨 끝에 추가)
            return existing_content.rstrip() + f"\n\n{category_section}\n\n{new_entry}"
    
    def _create_topic_entry(self, mail_data: Dict, classification: Dict, 
                           date_str: str, time_str: str) -> str:
        """주제별 파일 엔트리 생성"""
        content = []
        
        content.append(f"## 📅 {date_str} {time_str}")
        content.append(f"### {mail_data.get('subject', '제목 없음')}")
        content.append("")
        
        if classification.get('action_required'):
            content.append("⚠️ **조치 필요**")
            content.append("")
        
        content.append("**요약:**")
        content.append(classification.get('summary', '요약 없음'))
        content.append("")
        
        # 키워드/태그
        if classification.get('key_concepts') or classification.get('tags'):
            all_concepts = []
            if classification.get('key_concepts'):
                all_concepts.extend(classification['key_concepts'])
            if classification.get('tags'):
                all_concepts.extend(classification['tags'])
            
            unique_concepts = list(dict.fromkeys(all_concepts))
            if unique_concepts:
                concept_links = [f"[[{concept}]]" for concept in unique_concepts if concept.strip()]
                content.append("**관련 개념:** " + " · ".join(concept_links[:5]))
                content.append("")
        
        content.append("---")
        content.append("")
        
        return '\n'.join(content)
    
    def _add_to_processed_index(self, mail_id: str, mail_data: Dict, category: str):
        """처리된 메일 인덱스에 추가"""
        self.processed_index[mail_id] = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "subject": mail_data.get('subject', '')[:100],  # 100자로 제한
            "category": category,
            "checksum": self._calculate_content_checksum(mail_data)
        }
        self._save_processed_index()
    
    def _check_reorganization_needs(self):
        """카테고리 재편 필요성 확인"""
        try:
            reorganization_plan = self.category_manager.analyze_reorganization_needs()
            
            if reorganization_plan["needs_reorganization"]:
                logger.info(f"카테고리 재편 필요 감지:")
                logger.info(f"- 저빈도 카테고리: {len(reorganization_plan['low_frequency_categories'])}개")
                logger.info(f"- 병합 제안: {len(reorganization_plan['merge_suggestions'])}개")
                logger.info(f"- 총 카테고리 수: {reorganization_plan['total_categories']}개")
                
                # 자동 재편 실행 (향후 사용자 확인 기능 추가 예정)
                if len(reorganization_plan['low_frequency_categories']) > 0:
                    logger.info("자동 카테고리 재편 실행...")
                    result = self.category_manager.execute_reorganization(reorganization_plan, True)
                    if result["status"] == "success":
                        logger.info(f"카테고리 재편 완료: {len(result['actions_taken'])}개 작업 수행")
                        self._reorganize_files(result)
                        return {
                            "reorganized": True,
                            "actions": result['actions_taken'],
                            "plan": reorganization_plan
                        }
                
                return {
                    "reorganized": False,
                    "needs_reorganization": True,
                    "plan": reorganization_plan
                }
            
            return {
                "reorganized": False,
                "needs_reorganization": False
            }
        
        except Exception as e:
            logger.error(f"카테고리 재편 확인 실패: {e}")
            return {"reorganized": False, "error": str(e)}
    
    def _reorganize_files(self, reorganization_result: Dict):
        """파일 재편성"""
        try:
            # 제거된 카테고리 파일들을 기타로 병합
            for removed_category in reorganization_result.get("categories_removed", []):
                old_file = self.topics_dir / f"{self._sanitize_filename(removed_category)}{self.file_format}"
                if old_file.exists():
                    misc_file = self.topics_dir / f"기타{self.file_format}"
                    self._merge_topic_files(old_file, misc_file, "기타")
                    old_file.unlink()  # 원본 파일 삭제
                    logger.info(f"파일 재편: {removed_category} → 기타")
            
            # 병합된 카테고리 파일들 처리
            for merge_info in reorganization_result.get("categories_merged", []):
                from_categories = merge_info["from"]
                to_category = merge_info["to"]
                
                # 새 파일로 병합
                new_file = self.topics_dir / f"{self._sanitize_filename(to_category)}{self.file_format}"
                
                for old_category in from_categories:
                    old_file = self.topics_dir / f"{self._sanitize_filename(old_category)}{self.file_format}"
                    if old_file.exists():
                        self._merge_topic_files(old_file, new_file, to_category)
                        old_file.unlink()  # 원본 파일 삭제
                        logger.info(f"파일 병합: {old_category} → {to_category}")
        
        except Exception as e:
            logger.error(f"파일 재편성 실패: {e}")
    
    def _merge_topic_files(self, source_file: Path, target_file: Path, target_category: str):
        """주제 파일들 병합"""
        try:
            # 원본 파일 내용 읽기
            with open(source_file, 'r', encoding='utf-8') as f:
                source_content = f.read()
            
            # 헤더 제거 (첫 번째 --- 까지)
            lines = source_content.split('\n')
            content_start = 0
            for i, line in enumerate(lines):
                if line.strip() == "---":
                    content_start = i + 1
                    break
            
            source_body = '\n'.join(lines[content_start:]).strip()
            
            if target_file.exists():
                # 기존 파일에 추가
                with open(target_file, 'r', encoding='utf-8') as f:
                    target_content = f.read()
                
                # 기존 내용 끝에 새 내용 추가
                merged_content = target_content.rstrip() + '\n\n' + source_body
            else:
                # 새 파일 생성
                header = f"# {target_category}\n\n생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
                merged_content = header + source_body
            
            # 병합된 내용 저장
            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(merged_content)
        
        except Exception as e:
            logger.error(f"파일 병합 실패: {e}")
    
    def _sanitize_filename(self, text: str) -> str:
        """파일명으로 사용 가능한 문자로 변환"""
        import re
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = text.strip()
        return text or "기타"
    
    def get_processing_statistics(self) -> Dict:
        """처리 통계 반환"""
        total_processed = len(self.processed_index)
        if total_processed == 0:
            return {"total_processed": 0, "categories": {}, "recent_activity": []}
        
        # 카테고리별 통계
        category_stats = {}
        recent_activity = []
        
        for mail_id, info in self.processed_index.items():
            category = info["category"]
            if category not in category_stats:
                category_stats[category] = 0
            category_stats[category] += 1
            
            # 최근 5개 활동
            if len(recent_activity) < 5:
                recent_activity.append({
                    "date": info["date"],
                    "subject": info["subject"],
                    "category": category
                })
        
        # 카테고리 현황
        category_overview = self.category_manager.get_category_overview()
        
        return {
            "total_processed": total_processed,
            "categories": category_stats,
            "recent_activity": sorted(recent_activity, key=lambda x: x["date"], reverse=True),
            "category_overview": category_overview,
            "files_structure": {
                "topics_dir": str(self.topics_dir),
                "daily_dir": str(self.daily_dir),
                "topic_files": len(list(self.topics_dir.glob("*" + self.file_format))),
                "daily_files": len(list(self.daily_dir.glob("*" + self.file_format)))
            }
        }