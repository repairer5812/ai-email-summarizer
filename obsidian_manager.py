import os
from pathlib import Path
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class ObsidianManager:
    def __init__(self, base_path, file_format=".md"):
        """옵시디언 매니저 초기화"""
        self.base_path = Path(base_path)
        self.file_format = file_format
        
        # 기본 디렉토리 생성
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # DailyEmails 폴더 정의 (필요할 때만 생성)
        self.daily_folder = self.base_path / "DailyEmails"
    
    def save_mail(self, mail_data, classification):
        """메일을 DailyEmails/yyyy-mm-dd_주제 형식으로 저장"""
        try:
            # 실제로 파일을 저장할 때만 폴더 생성
            self.daily_folder.mkdir(parents=True, exist_ok=True)
            
            # 파일명 생성: yyyy-mm-dd_주제
            date_str = datetime.now().strftime("%Y-%m-%d")
            category = self._sanitize_filename(classification['category'])
            
            # DailyEmails 폴더에 직접 저장 (카테고리 폴더 없이)
            filename = f"{date_str}_{category}{self.file_format}"
            filepath = self.daily_folder / filename
            
            # 기존 파일이 있으면 추가, 없으면 생성
            if filepath.exists():
                content = self._append_mail_content(filepath, mail_data, classification)
            else:
                content = self._create_mail_content(mail_data, classification, date_str, category)
            
            # 파일 저장
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"메일 저장 완료: {filepath}")
            
        except Exception as e:
            logger.error(f"메일 저장 실패: {e}")
            raise
    
    def _sanitize_filename(self, text):
        """파일명으로 사용 가능한 문자로 변환"""
        # 특수문자 제거
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = text.strip()
        return text or "기타"
    
    def _create_mail_content(self, mail_data, classification, date_str, category):
        """새 파일 내용 생성"""
        if self.file_format == ".md":
            return self._create_markdown_content(mail_data, classification, date_str, category)
        else:
            return self._create_text_content(mail_data, classification, date_str, category)
    
    def _create_markdown_content(self, mail_data, classification, date_str, category):
        """마크다운 형식 내용 생성"""
        content = []
        
        # 헤더
        content.append(f"# {category} - {date_str}")
        content.append("")
        content.append(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")
        
        # 메일 내용
        content.append(f"## {mail_data.get('subject', '제목 없음')}")
        content.append("")
        content.append(f"**발신일:** {mail_data.get('date', date_str)}")
        
        if classification.get('action_required'):
            content.append("**⚠️ 조치 필요**")
        
        content.append("")
        content.append("### 요약")
        content.append(classification.get('summary', '요약 없음'))
        content.append("")
        
        if mail_data.get('attachments'):
            content.append("### 첨부파일")
            for attachment in mail_data['attachments']:
                content.append(f"- {attachment}")
            content.append("")
        
        # 태그
        if classification.get('tags'):
            tags = ' '.join([f"#{tag}" for tag in classification['tags']])
            content.append(f"**태그:** {tags}")
        
        # 주요 개념 백링크 섹션 추가
        content.append("")
        content.append("### 주요 개념")
        
        # key_concepts와 tags를 합쳐서 백링크 생성
        all_concepts = []
        if classification.get('key_concepts'):
            all_concepts.extend(classification['key_concepts'])
        if classification.get('tags'):
            all_concepts.extend(classification['tags'])
        
        # 중복 제거하고 백링크 생성
        unique_concepts = list(dict.fromkeys(all_concepts))  # 순서 유지하면서 중복 제거
        if unique_concepts:
            concept_links = [f"[[{concept}]]" for concept in unique_concepts if concept and len(concept.strip()) > 1]
            if concept_links:
                # 5개씩 줄바꿈해서 표시
                for i in range(0, len(concept_links), 5):
                    line_concepts = concept_links[i:i+5]
                    content.append(" · ".join(line_concepts))
        else:
            content.append("관련 개념이 없습니다.")
        
        content.append("")
        content.append("---")
        content.append("")
        
        return '\n'.join(content)
    
    def _create_text_content(self, mail_data, classification, date_str, category):
        """텍스트 형식 내용 생성"""
        content = []
        
        content.append(f"{category} - {date_str}")
        content.append("=" * 50)
        content.append(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")
        
        content.append(f"제목: {mail_data.get('subject', '제목 없음')}")
        content.append(f"발신일: {mail_data.get('date', date_str)}")
        
        if classification.get('action_required'):
            content.append("*** 조치 필요 ***")
        
        content.append("")
        content.append("요약:")
        content.append(classification.get('summary', '요약 없음'))
        content.append("")
        
        if mail_data.get('attachments'):
            content.append("첨부파일:")
            for attachment in mail_data['attachments']:
                content.append(f"  - {attachment}")
            content.append("")
        
        if classification.get('tags'):
            content.append(f"태그: {', '.join(classification['tags'])}")
        
        content.append("")
        content.append("-" * 50)
        content.append("")
        
        return '\n'.join(content)
    
    def _append_mail_content(self, filepath, mail_data, classification):
        """기존 파일에 내용 추가"""
        with open(filepath, 'r', encoding='utf-8') as f:
            existing_content = f.read()
        
        # 새 메일 내용 생성 (헤더 제외)
        if self.file_format == ".md":
            new_content = self._create_markdown_mail_entry(mail_data, classification)
        else:
            new_content = self._create_text_mail_entry(mail_data, classification)
        
        return existing_content + new_content
    
    def _create_markdown_mail_entry(self, mail_data, classification):
        """마크다운 메일 항목 생성"""
        content = []
        
        content.append(f"## {mail_data.get('subject', '제목 없음')}")
        content.append("")
        content.append(f"**발신일:** {mail_data.get('date', '')}")
        
        if classification.get('action_required'):
            content.append("**⚠️ 조치 필요**")
        
        content.append("")
        content.append("### 요약")
        content.append(classification.get('summary', '요약 없음'))
        content.append("")
        
        if classification.get('tags'):
            tags = ' '.join([f"#{tag}" for tag in classification['tags']])
            content.append(f"**태그:** {tags}")
        
        # 개별 메일에도 주요 개념 백링크 추가
        content.append("")
        content.append("#### 관련 개념")
        
        # key_concepts와 tags를 합쳐서 백링크 생성
        all_concepts = []
        if classification.get('key_concepts'):
            all_concepts.extend(classification['key_concepts'])
        if classification.get('tags'):
            all_concepts.extend(classification['tags'])
        
        # 중복 제거하고 백링크 생성
        unique_concepts = list(dict.fromkeys(all_concepts))
        if unique_concepts:
            concept_links = [f"[[{concept}]]" for concept in unique_concepts if concept and len(concept.strip()) > 1]
            if concept_links:
                content.append(" · ".join(concept_links))
        else:
            content.append("관련 개념이 없습니다.")
        
        content.append("")
        content.append("---")
        content.append("")
        
        return '\n'.join(content)
    
    def _create_text_mail_entry(self, mail_data, classification):
        """텍스트 메일 항목 생성"""
        content = []
        
        content.append(f"제목: {mail_data.get('subject', '제목 없음')}")
        content.append(f"발신일: {mail_data.get('date', '')}")
        content.append(f"요약: {classification.get('summary', '요약 없음')}")
        
        if classification.get('tags'):
            content.append(f"태그: {', '.join(classification['tags'])}")
        
        content.append("-" * 50)
        content.append("")
        
        return '\n'.join(content)
    
