import schedule
import time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self):
        """스케줄러 초기화"""
        self.scheduler_thread = None
        self.running = False
        
    def setup_schedule(self, time_str, job_func):
        """스케줄 설정"""
        # 기존 스케줄 정지
        self.stop()
        
        # 새 스케줄 설정
        schedule.clear()
        schedule.every().day.at(time_str).do(job_func)
        
        # 스케줄러 스레드 시작
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        
        logger.info(f"스케줄 설정 완료: 매일 {time_str}")
    
    def _run_scheduler(self):
        """스케줄러 실행"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)
    
    def stop(self):
        """스케줄러 정지"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        schedule.clear()
        logger.info("스케줄러 정지")