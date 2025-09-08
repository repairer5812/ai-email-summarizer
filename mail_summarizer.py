#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re

logger = logging.getLogger(__name__)

class MailSummarizer:
    def __init__(self, base_path=None):
        """메일 요약기 초기화
        Args:
            base_path: 사용자가 설정한 저장 경로 (기본값: 현재 디렉토리)
        """
        self.base_path = Path(base_path) if base_path else Path(".")
        
        # 기본 디렉토리 생성
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # DailyMails 디렉토리 (날짜별 요약) - 필요할 때만 생성
        self.daily_dir = self.base_path / "DailyMails"
        
        # TopicsEmail 디렉토리 (주제별 누적 요약) - 필요할 때만 생성
        self.topics_dir = self.base_path / "TopicsEmail"
        
    def create_summary_report(self, classified_mails):
        """메일들을 요약하고 주제별로 분류하여 마크다운 보고서 생성"""
        try:
            # 메일이 없으면 폴더를 생성하지 않음
            if not classified_mails:
                logger.info("처리할 메일이 없어 폴더를 생성하지 않습니다.")
                return None
                
            # 실제로 사용할 때만 폴더 생성
            self.daily_dir.mkdir(parents=True, exist_ok=True)
            self.topics_dir.mkdir(parents=True, exist_ok=True)
            
            # 날짜별 파일명 생성 (yyyy-mm-dd.md 형식)
            today = datetime.now().strftime('%Y-%m-%d')
            daily_filename = f"{today}.md"
            daily_filepath = self.daily_dir / daily_filename
            
            # 주제별 분류
            categorized_mails = self._categorize_mails(classified_mails)
            
            # 키워드 추출
            all_keywords = self._extract_keywords(classified_mails)
            
            # 날짜별 마크다운 보고서 생성
            daily_report = self._generate_markdown_report(categorized_mails, all_keywords, today)
            
            # 날짜별 파일 저장
            with open(daily_filepath, 'w', encoding='utf-8') as f:
                f.write(daily_report)
            
            logger.info(f"날짜별 메일 요약 저장: {daily_filepath}")
            
            # 주제별 누적 파일 생성 및 업데이트
            self._update_topic_files(categorized_mails, today)
            
            return str(daily_filepath)
            
        except Exception as e:
            logger.error(f"요약 보고서 생성 실패: {e}")
            raise
    
    def _categorize_mails(self, classified_mails):
        """메일을 카테고리별로 분류"""
        categories = defaultdict(list)
        
        for mail_data, classification in classified_mails:
            category = classification.get('category', '기타')
            categories[category].append({
                'mail_data': mail_data,
                'classification': classification
            })
        
        return categories
    
    def _extract_keywords(self, classified_mails):
        """모든 메일에서 키워드 추출 및 빈도 계산"""
        keyword_freq = defaultdict(int)
        
        for mail_data, classification in classified_mails:
            # 태그에서 키워드 추출
            for tag in classification.get('tags', []):
                if tag and len(tag.strip()) > 1:  # 빈 태그 제외
                    keyword_freq[tag.strip()] += 1
            
            # key_concepts에서 키워드 추출 (백링크용)
            for concept in classification.get('key_concepts', []):
                if concept and len(concept.strip()) > 1:
                    keyword_freq[concept.strip()] += 2  # 핵심 개념은 가중치 2배
            
            # 제목과 내용에서 추가 키워드 추출
            content = f"{mail_data.get('subject', '')} {mail_data.get('content', '')}"
            additional_keywords = self._extract_additional_keywords(content)
            for keyword in additional_keywords:
                keyword_freq[keyword] += 1
        
        # 빈도가 높은 순으로 정렬하여 상위 25개 반환
        sorted_keywords = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)
        return [keyword for keyword, freq in sorted_keywords[:25] if freq >= 1]
    
    def _update_topic_files(self, categorized_mails, today):
        """주제별 누적 파일 업데이트 (최신 내용이 상단에 위치)"""
        for category, mails in categorized_mails.items():
            if not mails:  # 빈 카테고리 건너뛰기
                continue
                
            # 주제별 파일명 (특수문자 제거)
            safe_category = self._sanitize_filename(category)
            topic_filename = f"{safe_category}.md"
            topic_filepath = self.topics_dir / topic_filename
            
            # 오늘 날짜의 새로운 내용 생성
            new_content = self._generate_topic_content(category, mails, today)
            
            # 기존 파일이 있으면 상단에 추가, 없으면 새로 생성
            if topic_filepath.exists():
                # 기존 내용 읽기
                with open(topic_filepath, 'r', encoding='utf-8') as f:
                    existing_content = f.read()
                
                # 새 내용을 상단에 추가 (최신 내용이 맨 위에)
                combined_content = new_content + "\n\n---\n\n" + existing_content
            else:
                # 새 파일 생성
                header = f"# {category} 주제별 요약\n\n"
                header += f"> 이 파일은 '{category}' 카테고리의 메일들을 주제별로 누적하여 정리한 파일입니다.\n"
                header += f"> 최신 내용이 항상 맨 위에 나타납니다.\n\n"
                combined_content = header + new_content
            
            # 파일 저장
            with open(topic_filepath, 'w', encoding='utf-8') as f:
                f.write(combined_content)
            
            logger.info(f"주제별 누적 파일 업데이트: {topic_filepath}")
    
    def _sanitize_filename(self, filename):
        """파일명에 사용할 수 없는 문자 제거"""
        import re
        # 윈도우에서 사용할 수 없는 문자들 제거
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
        safe_name = safe_name.strip().replace(' ', '_')
        return safe_name if safe_name else '기타'
    
    def _generate_topic_content(self, category, mails, today):
        """주제별 내용 생성"""
        content_lines = []
        content_lines.append(f"## {today} - {category} ({len(mails)}건)\n")
        
        for i, mail_info in enumerate(mails, 1):
            mail_data = mail_info['mail_data']
            classification = mail_info['classification']
            
            content_lines.append(f"### {i}. {mail_data.get('subject', '제목 없음')}")
            content_lines.append(f"- **발신자:** {mail_data.get('sender', '알 수 없음')}")
            content_lines.append(f"- **날짜:** {mail_data.get('date', '날짜 없음')}")
            
            # 요약
            summary = classification.get('summary', '요약 없음')
            content_lines.append(f"- **요약:** {summary}")
            
            # 태그 (백링크 형태)
            if classification.get('tags'):
                tags_with_links = [f"[[{tag}]]" for tag in classification.get('tags', [])]
                content_lines.append(f"- **태그:** {', '.join(tags_with_links)}")
            
            # 주요 개념 (백링크 형태)
            if classification.get('key_concepts'):
                concepts_with_links = [f"[[{concept}]]" for concept in classification.get('key_concepts', [])]
                content_lines.append(f"- **주요 개념:** {', '.join(concepts_with_links)}")
            
            # URL과 출처
            if classification.get('urls'):
                content_lines.append(f"- **참조 URL:** {', '.join(classification.get('urls', []))}")
            if classification.get('sources'):
                content_lines.append(f"- **출처:** {', '.join(classification.get('sources', []))}")
            
            content_lines.append("")  # 빈 줄 추가
        
        return "\n".join(content_lines)
    
    def _extract_additional_keywords(self, content):
        """텍스트에서 추가 키워드 추출"""
        # 한글 키워드 패턴
        korean_keywords = []
        
        # 일반적인 비즈니스/기술 키워드들
        business_keywords = [
            '프로젝트', '개발', '시스템', '서비스', '플랫폼', '솔루션',
            '마케팅', '영업', '고객', '매출', '수익', '비용', '예산',
            'AI', '인공지능', '머신러닝', '빅데이터', '클라우드', 'IoT',
            '보안', '네트워크', '데이터베이스', '앱', '웹사이트',
            '회의', '미팅', '보고서', '분석', '전략', '계획'
        ]
        
        content_lower = content.lower()
        found_keywords = []
        
        for keyword in business_keywords:
            if keyword.lower() in content_lower or keyword in content:
                found_keywords.append(keyword)
        
        return found_keywords[:5]  # 최대 5개까지
    
    def _generate_markdown_report(self, categorized_mails, keywords, today):
        """마크다운 형식의 보고서 생성"""
        report_lines = []
        
        # 헤더
        report_lines.append(f"# 📧 일일 메일 요약 보고서")
        report_lines.append(f"**날짜:** {today}")
        report_lines.append(f"**생성시간:** {datetime.now().strftime('%H:%M:%S')}")
        report_lines.append("")
        
        # 전체 요약
        total_mails = sum(len(mails) for mails in categorized_mails.values())
        report_lines.append("## 📊 전체 요약")
        report_lines.append(f"- **총 메일 수:** {total_mails}개")
        report_lines.append(f"- **카테고리 수:** {len(categorized_mails)}개")
        report_lines.append("")
        
        # 카테고리별 요약 (주제별 분류)
        report_lines.append("## 🗂️ 주제별 메일 분류")
        report_lines.append("")
        
        # 카테고리 우선순위로 정렬
        category_priority = {
            '업무지시': 1, '공지사항': 2, '미팅일정': 3, '보고서': 4,
            '기술동향': 5, '경제뉴스': 6, '기타': 7
        }
        
        sorted_categories = sorted(categorized_mails.items(), 
                                 key=lambda x: category_priority.get(x[0], 99))
        
        for category, mails in sorted_categories:
            report_lines.append(f"### 📌 {category} ({len(mails)}개)")
            report_lines.append("")
            
            # 액션 필요한 메일을 우선으로 정렬
            action_required_mails = [m for m in mails if m['classification'].get('action_required')]
            normal_mails = [m for m in mails if not m['classification'].get('action_required')]
            
            all_mails = action_required_mails + normal_mails
            
            for mail_info in all_mails[:10]:  # 각 카테고리별 최대 10개까지
                mail_data = mail_info['mail_data']
                classification = mail_info['classification']
                
                # 액션 필요 여부 표시
                action_icon = "⚡" if classification.get('action_required') else ""
                
                report_lines.append(f"**{action_icon} {mail_data.get('subject', '제목 없음')}**")
                report_lines.append(f"- **발신일:** {mail_data.get('date', '날짜 불명')}")
                report_lines.append(f"- **요약:** {classification.get('summary', '요약 없음')}")
                
                # 태그 표시 (백링크 형태)
                if classification.get('tags'):
                    tags_with_links = [f"[[{tag}]]" for tag in classification.get('tags', [])]
                    report_lines.append(f"- **태그:** {', '.join(tags_with_links)}")
                
                # 주요 개념 표시 (백링크 형태)
                if classification.get('key_concepts'):
                    concepts_with_links = [f"[[{concept}]]" for concept in classification.get('key_concepts', [])]
                    report_lines.append(f"- **주요 개념:** {', '.join(concepts_with_links)}")
                
                # URL과 출처 표시
                if classification.get('urls'):
                    report_lines.append(f"- **참조 URL:** {', '.join(classification.get('urls', []))}")
                if classification.get('sources'):
                    report_lines.append(f"- **출처:** {', '.join(classification.get('sources', []))}")
                
                report_lines.append("")
            
            if len(mails) > 10:
                report_lines.append(f"*...및 {len(mails) - 10}개 추가 메일*")
                report_lines.append("")
            
            report_lines.append("---")
            report_lines.append("")
        
        # 주요 개념 (키워드 백링크)
        if keywords:
            report_lines.append("## 🔑 주요 개념")
            report_lines.append("")
            
            # 키워드를 백링크 형태로 나열 (5개씩 줄바꿈)
            keyword_links = [f"[[{keyword}]]" for keyword in keywords]
            
            for i in range(0, len(keyword_links), 5):
                line_keywords = keyword_links[i:i+5]
                report_lines.append(" · ".join(line_keywords))
                report_lines.append("")
        
        # 통계 정보
        report_lines.append("## 📈 상세 통계")
        report_lines.append("")
        
        # 카테고리별 통계
        report_lines.append("### 카테고리별 분포")
        for category, mails in sorted_categories:
            percentage = (len(mails) / total_mails * 100) if total_mails > 0 else 0
            report_lines.append(f"- **{category}:** {len(mails)}개 ({percentage:.1f}%)")
        report_lines.append("")
        
        # 액션 필요 메일 통계
        action_required_count = 0
        
        for mails in categorized_mails.values():
            for mail_info in mails:
                classification = mail_info['classification']
                if classification.get('action_required'):
                    action_required_count += 1
        
        report_lines.append("### 액션 필요 메일")
        percentage = (action_required_count / total_mails * 100) if total_mails > 0 else 0
        report_lines.append(f"- **액션 필요:** {action_required_count}개 ({percentage:.1f}%)")
        report_lines.append(f"- **정보성 메일:** {total_mails - action_required_count}개 ({100 - percentage:.1f}%)")
        
        report_lines.append("")
        report_lines.append("---")
        report_lines.append(f"*보고서 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        return "\n".join(report_lines)