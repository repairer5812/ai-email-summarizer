#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import logging
from datetime import datetime
from pathlib import Path
import threading

# Windows 환경에서 한글 출력을 위한 인코딩 설정
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 유틸리티 모듈
from utils import check_environment

# GUI 모듈
from gui import MailClassifierGUI
from scheduler import SchedulerManager

# 새로운 요약 모듈
from mail_summarizer import MailSummarizer

# 로깅 설정
def setup_logging():
    """로깅 설정"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"mail_classifier_{datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def main():
    """메인 실행 함수"""
    print("🚀 웹메일요약 시스템을 시작합니다...")
    print()
    
    # 실행 환경 확인 및 설정
    env_info = check_environment()
    print()
    
    logger = setup_logging()
    logger.info("=== 메일 분류 시스템 시작 ===")
    
    try:
        # GUI 실행
        app = MailClassifierGUI()
        app.run()
        
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()