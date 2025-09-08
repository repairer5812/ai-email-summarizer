import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path
import re
from typing import Dict, List, Tuple, Optional
import difflib

logger = logging.getLogger(__name__)

class DynamicCategoryManager:
    def __init__(self, base_path: str):
        """동적 카테고리 관리자 초기화"""
        self.base_path = Path(base_path)
        self.max_categories = 10
        self.merge_threshold_days = 30  # 30일간 없으면 재편 고려
        self.min_frequency = 2  # 최소 2회 이상
        self.similarity_threshold = 0.7  # 카테고리 유사도 임계값
        
        # 파일 경로 설정
        self.stats_file = self.base_path / "category_stats.json"
        self.reorganization_log = self.base_path / "reorganization_history.json"
        
        # 통계 데이터 로드
        self.category_stats = self._load_category_stats()
        self.reorganization_history = self._load_reorganization_history()
        
    def _load_category_stats(self) -> Dict:
        """카테고리 통계 로드"""
        try:
            if self.stats_file.exists():
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"카테고리 통계 로드 실패: {e}")
            return {}
    
    def _load_reorganization_history(self) -> List:
        """재편 이력 로드"""
        try:
            if self.reorganization_log.exists():
                with open(self.reorganization_log, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"재편 이력 로드 실패: {e}")
            return []
    
    def _save_category_stats(self):
        """카테고리 통계 저장"""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.category_stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"카테고리 통계 저장 실패: {e}")
    
    def _save_reorganization_history(self):
        """재편 이력 저장"""
        try:
            with open(self.reorganization_log, 'w', encoding='utf-8') as f:
                json.dump(self.reorganization_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"재편 이력 저장 실패: {e}")
    
    def update_category_stats(self, category: str, mail_data: Dict):
        """카테고리 통계 업데이트"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        if category not in self.category_stats:
            self.category_stats[category] = {
                "count": 0,
                "first_seen": current_date,
                "last_seen": current_date,
                "keywords": [],
                "recent_subjects": []
            }
        
        stats = self.category_stats[category]
        stats["count"] += 1
        stats["last_seen"] = current_date
        
        # 키워드 추출 및 업데이트
        keywords = self._extract_keywords(mail_data.get('subject', ''))
        stats["keywords"].extend(keywords)
        stats["keywords"] = list(set(stats["keywords"]))[:10]  # 상위 10개만 유지
        
        # 최근 제목 저장 (최대 5개)
        subject = mail_data.get('subject', '')[:50]  # 50자로 제한
        if subject not in stats["recent_subjects"]:
            stats["recent_subjects"].insert(0, subject)
            stats["recent_subjects"] = stats["recent_subjects"][:5]
        
        self._save_category_stats()
        logger.info(f"카테고리 통계 업데이트: {category} (총 {stats['count']}건)")
    
    def _extract_keywords(self, text: str) -> List[str]:
        """텍스트에서 주요 키워드 추출"""
        if not text:
            return []
        
        # 한글, 영문, 숫자만 추출
        words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', text)
        
        # 불용어 제거
        stop_words = {'메일', '알림', '공지', '안내', '확인', '요청', '관련', '대한', '에서', '으로', '에게', '에도'}
        keywords = [word for word in words if word not in stop_words and len(word) >= 2]
        
        return keywords[:5]  # 상위 5개만 반환
    
    def get_category_recommendation(self, mail_data: Dict) -> Dict:
        """메일에 대한 카테고리 추천"""
        subject = mail_data.get('subject', '')
        content = mail_data.get('content', '')[:200]  # 내용 일부만 사용
        
        # 기존 카테고리와의 유사도 계산
        scores = {}
        for category, stats in self.category_stats.items():
            if category == "기타":
                continue
                
            score = self._calculate_similarity(subject + " " + content, stats)
            if score > 0.3:  # 최소 유사도 임계값
                scores[category] = score
        
        # 새로운 트렌드 감지
        new_trend = self._detect_new_trend(subject, content)
        
        if scores:
            # 가장 유사한 카테고리 추천
            best_category = max(scores.items(), key=lambda x: x[1])
            return {
                "suggested_category": best_category[0],
                "confidence": best_category[1],
                "alternative_categories": [cat for cat, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[1:3]],
                "new_trend_detected": new_trend is not None,
                "new_trend_suggestion": new_trend
            }
        else:
            # 기존 카테고리와 매치되지 않음
            return {
                "suggested_category": new_trend if new_trend else "기타",
                "confidence": 0.5 if new_trend else 0.1,
                "alternative_categories": [],
                "new_trend_detected": new_trend is not None,
                "new_trend_suggestion": new_trend
            }
    
    def _calculate_similarity(self, text: str, category_stats: Dict) -> float:
        """텍스트와 카테고리 통계 간의 유사도 계산"""
        text_keywords = set(self._extract_keywords(text.lower()))
        category_keywords = set([k.lower() for k in category_stats.get("keywords", [])])
        
        if not category_keywords:
            return 0.0
        
        # 키워드 교집합 비율
        intersection = len(text_keywords.intersection(category_keywords))
        union = len(text_keywords.union(category_keywords))
        
        if union == 0:
            return 0.0
        
        keyword_score = intersection / union
        
        # 제목 유사도 (최근 제목들과 비교)
        subject_score = 0.0
        recent_subjects = category_stats.get("recent_subjects", [])
        if recent_subjects:
            similarities = [difflib.SequenceMatcher(None, text, subject).ratio() for subject in recent_subjects]
            subject_score = max(similarities) if similarities else 0.0
        
        # 가중 평균
        return keyword_score * 0.7 + subject_score * 0.3
    
    def _detect_new_trend(self, subject: str, content: str) -> Optional[str]:
        """새로운 트렌드 감지"""
        text = subject + " " + content
        keywords = self._extract_keywords(text)
        
        if not keywords:
            return None
        
        # "기타" 카테고리에서 누적된 키워드 패턴 분석
        misc_stats = self.category_stats.get("기타", {})
        misc_keywords = misc_stats.get("keywords", [])
        
        # 키워드 빈도 분석 (실제로는 더 정교한 분석 필요)
        keyword_counter = Counter(misc_keywords)
        
        # 주요 키워드가 특정 임계값을 넘으면 새 카테고리 제안
        for keyword in keywords[:2]:  # 상위 2개 키워드만 검사
            if keyword_counter.get(keyword, 0) >= 3:  # 3번 이상 나타난 키워드
                # 관련 키워드들과 조합해서 새 카테고리명 생성
                related_keywords = [k for k, v in keyword_counter.items() if v >= 2 and k != keyword]
                if related_keywords:
                    new_category = f"{keyword}/{related_keywords[0]}"
                else:
                    new_category = keyword
                
                return new_category
        
        return None
    
    def analyze_reorganization_needs(self) -> Dict:
        """재편 필요성 분석"""
        current_date = datetime.now()
        reorganization_plan = {
            "needs_reorganization": False,
            "low_frequency_categories": [],
            "merge_suggestions": [],
            "new_category_suggestions": [],
            "total_categories": len(self.category_stats)
        }
        
        # 1. 저빈도 카테고리 식별
        for category, stats in self.category_stats.items():
            if category == "기타":
                continue
                
            last_seen = datetime.strptime(stats["last_seen"], "%Y-%m-%d")
            days_since_last = (current_date - last_seen).days
            
            if days_since_last > self.merge_threshold_days or stats["count"] < self.min_frequency:
                reorganization_plan["low_frequency_categories"].append({
                    "category": category,
                    "count": stats["count"],
                    "days_since_last": days_since_last
                })
        
        # 2. 유사 카테고리 병합 제안
        categories = [cat for cat in self.category_stats.keys() if cat != "기타"]
        for i, cat1 in enumerate(categories):
            for cat2 in categories[i+1:]:
                similarity = self._calculate_category_similarity(cat1, cat2)
                if similarity > self.similarity_threshold:
                    reorganization_plan["merge_suggestions"].append({
                        "category1": cat1,
                        "category2": cat2,
                        "similarity": similarity,
                        "combined_count": self.category_stats[cat1]["count"] + self.category_stats[cat2]["count"]
                    })
        
        # 3. 카테고리 수 제한 검사
        if len(self.category_stats) > self.max_categories:
            reorganization_plan["needs_reorganization"] = True
        
        # 4. 저빈도 카테고리나 병합 제안이 있으면 재편 필요
        if reorganization_plan["low_frequency_categories"] or reorganization_plan["merge_suggestions"]:
            reorganization_plan["needs_reorganization"] = True
        
        return reorganization_plan
    
    def _calculate_category_similarity(self, cat1: str, cat2: str) -> float:
        """두 카테고리 간의 유사도 계산"""
        stats1 = self.category_stats.get(cat1, {})
        stats2 = self.category_stats.get(cat2, {})
        
        keywords1 = set([k.lower() for k in stats1.get("keywords", [])])
        keywords2 = set([k.lower() for k in stats2.get("keywords", [])])
        
        if not keywords1 or not keywords2:
            return 0.0
        
        intersection = len(keywords1.intersection(keywords2))
        union = len(keywords1.union(keywords2))
        
        return intersection / union if union > 0 else 0.0
    
    def execute_reorganization(self, reorganization_plan: Dict, user_approved: bool = True) -> Dict:
        """재편 실행"""
        if not user_approved:
            return {"status": "cancelled", "message": "사용자가 재편을 취소했습니다."}
        
        result = {
            "status": "success",
            "actions_taken": [],
            "files_moved": [],
            "categories_merged": [],
            "categories_removed": []
        }
        
        try:
            # 1. 저빈도 카테고리 처리 (기타로 병합)
            for low_freq in reorganization_plan.get("low_frequency_categories", []):
                category = low_freq["category"]
                self._merge_category_to_misc(category)
                result["categories_removed"].append(category)
                result["actions_taken"].append(f"'{category}' 카테고리를 '기타'로 병합")
            
            # 2. 유사 카테고리 병합
            for merge_suggestion in reorganization_plan.get("merge_suggestions", []):
                cat1 = merge_suggestion["category1"]
                cat2 = merge_suggestion["category2"]
                new_category = f"{cat1}/{cat2}"
                
                self._merge_categories(cat1, cat2, new_category)
                result["categories_merged"].append({"from": [cat1, cat2], "to": new_category})
                result["actions_taken"].append(f"'{cat1}'과 '{cat2}'를 '{new_category}'로 병합")
            
            # 재편 이력 저장
            self.reorganization_history.append({
                "date": datetime.now().isoformat(),
                "plan": reorganization_plan,
                "result": result
            })
            self._save_reorganization_history()
            
            logger.info(f"카테고리 재편 완료: {len(result['actions_taken'])}개 작업 수행")
            
        except Exception as e:
            logger.error(f"카테고리 재편 실패: {e}")
            result["status"] = "error"
            result["message"] = str(e)
        
        return result
    
    def _merge_category_to_misc(self, category: str):
        """카테고리를 기타로 병합"""
        if category not in self.category_stats:
            return
        
        # 통계 병합
        if "기타" not in self.category_stats:
            self.category_stats["기타"] = {
                "count": 0,
                "first_seen": datetime.now().strftime("%Y-%m-%d"),
                "last_seen": datetime.now().strftime("%Y-%m-%d"),
                "keywords": [],
                "recent_subjects": []
            }
        
        misc_stats = self.category_stats["기타"]
        cat_stats = self.category_stats[category]
        
        misc_stats["count"] += cat_stats["count"]
        misc_stats["keywords"].extend(cat_stats["keywords"])
        misc_stats["keywords"] = list(set(misc_stats["keywords"]))[:10]
        misc_stats["recent_subjects"] = (misc_stats["recent_subjects"] + cat_stats["recent_subjects"])[:5]
        
        # 원본 카테고리 제거
        del self.category_stats[category]
        self._save_category_stats()
    
    def _merge_categories(self, cat1: str, cat2: str, new_category: str):
        """두 카테고리를 새 카테고리로 병합"""
        if cat1 not in self.category_stats or cat2 not in self.category_stats:
            return
        
        stats1 = self.category_stats[cat1]
        stats2 = self.category_stats[cat2]
        
        # 새 카테고리 생성
        self.category_stats[new_category] = {
            "count": stats1["count"] + stats2["count"],
            "first_seen": min(stats1["first_seen"], stats2["first_seen"]),
            "last_seen": max(stats1["last_seen"], stats2["last_seen"]),
            "keywords": list(set(stats1["keywords"] + stats2["keywords"]))[:10],
            "recent_subjects": (stats1["recent_subjects"] + stats2["recent_subjects"])[:5]
        }
        
        # 원본 카테고리들 제거
        del self.category_stats[cat1]
        del self.category_stats[cat2]
        self._save_category_stats()
    
    def get_category_overview(self) -> Dict:
        """카테고리 현황 요약"""
        total_mails = sum(stats["count"] for stats in self.category_stats.values())
        
        overview = {
            "total_categories": len(self.category_stats),
            "total_mails": total_mails,
            "categories": []
        }
        
        # 빈도순으로 정렬
        sorted_categories = sorted(
            self.category_stats.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )
        
        for category, stats in sorted_categories:
            last_seen = datetime.strptime(stats["last_seen"], "%Y-%m-%d")
            days_ago = (datetime.now() - last_seen).days
            
            overview["categories"].append({
                "name": category,
                "count": stats["count"],
                "percentage": round(stats["count"] / total_mails * 100, 1) if total_mails > 0 else 0,
                "last_seen": stats["last_seen"],
                "days_ago": days_ago,
                "keywords": stats["keywords"][:5],
                "status": "active" if days_ago <= 7 else "inactive" if days_ago <= 30 else "stale"
            })
        
        return overview