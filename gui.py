import customtkinter as ctk
import json
import os
from pathlib import Path
from datetime import datetime, time
import threading
from tkinter import filedialog, messagebox
import logging

from utils import get_config_path
from mail_collector import MailCollector
from ai_classifier import AIClassifier
from obsidian_manager import ObsidianManager
from file_manager import EnhancedFileManager
from scheduler import SchedulerManager
from mail_summarizer import MailSummarizer
from security_manager import SecurityManager

logger = logging.getLogger(__name__)

class MailClassifierGUI:
    def __init__(self):
        """GUI 초기화"""
        # utils를 사용해 안전한 설정 파일 경로 설정
        self.config_file = get_config_path()
        print(f"📄 Config 파일 경로: {self.config_file}")
        
        # 보안 관리자 초기화
        self.security_manager = SecurityManager()
        
        # 기존 평문 설정 마이그레이션
        migration_result = self.security_manager.migrate_existing_config()
        if migration_result:
            print("🔒 보안: 민감한 정보가 암호화되었습니다.")
        
        self.config = self.load_config()
        
        # 메인 윈도우 설정
        self.root = ctk.CTk()
        self.root.title("Dauoffice 메일 분류 시스템")
        self.root.geometry("900x800")  # 창 크기를 늘려서 모든 버튼이 보이도록 함
        
        # 테마 설정
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        
        # 컴포넌트 초기화
        self.mail_collector = None
        self.ai_classifier = None
        self.obsidian_manager = None
        self.mail_summarizer = None  # 나중에 사용자 경로로 초기화
        self.scheduler = SchedulerManager()
        
        # 중지 기능 관련
        self.is_running = False
        self.stop_requested = False
        
        self.setup_ui()
        self.load_settings()
        
    def load_config(self):
        """설정 파일 로드 (보안 관리자 사용)"""
        try:
            # 보안 관리자를 통해 복호화된 설정 로드
            config = self.security_manager.decrypt_config()
            
            # 기존 "obsidian" 설정을 "output"으로 migration
            if "obsidian" in config and "output" not in config:
                config["output"] = config["obsidian"]
                del config["obsidian"]
                print("Debug: obsidian -> output migration 완료")
            
            # 누락된 키 보완
            if "output" not in config:
                config["output"] = {"path": "", "file_format": ".md"}
                
            # OpenAI 설정 추가 (없는 경우)
            if "openai" not in config:
                config["openai"] = {"api_key": ""}
                
            # 스케줄 설정 추가 (없는 경우)
            if "schedule" not in config:
                config["schedule"] = {"enabled": False, "time": "09:00"}
            
            return config
            
        except Exception as e:
            logger.error(f"설정 로드 실패: {e}")
            return {
                "dauoffice": {"username": "", "password": "", "target_folder": ""},
                "gemini": {"api_key": ""},
                "openai": {"api_key": ""},
                "output": {"path": "", "file_format": ".md"},
                "schedule": {"enabled": False, "time": "09:00"},
                "last_run": None,
                "processed_mails": []
            }
    
    def save_config(self):
        """설정 파일 저장 (보안 관리자 사용)"""
        try:
            print(f"Debug: 보안 config 저장 시도 - 파일경로: {os.path.abspath(self.config_file)}")
            
            # 보안 관리자를 통해 암호화하여 저장
            success = self.security_manager.encrypt_config(self.config)
            
            if success:
                print("🔒 Debug: 설정이 안전하게 암호화되어 저장되었습니다.")
            else:
                print("⚠️ Debug: 설정 암호화 저장 실패, 기본 방식으로 저장")
                # 실패 시 기본 방식으로 저장 (민감한 정보는 마스킹)
                safe_config = self._create_safe_config_for_fallback()
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(safe_config, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"설정 저장 실패: {e}")
            print(f"Debug: config 저장 실패: {e}")
            raise e
    
    def _create_safe_config_for_fallback(self):
        """대안 저장을 위한 안전한 설정 생성"""
        safe_config = self.config.copy()
        
        # 민감한 정보 마스킹
        if "dauoffice" in safe_config and safe_config["dauoffice"].get("password"):
            safe_config["dauoffice"]["password"] = "***PROTECTED***"
        
        if "gemini" in safe_config and safe_config["gemini"].get("api_key"):
            safe_config["gemini"]["api_key"] = "***PROTECTED***"
            
        if "openai" in safe_config and safe_config["openai"].get("api_key"):
            safe_config["openai"]["api_key"] = "***PROTECTED***"
        
        return safe_config
    
    def setup_ui(self):
        """UI 구성"""
        # 탭 생성
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)  # 패딩 줄임
        
        # 탭 추가
        self.tab_settings = self.tabview.add("⚙️ 설정")
        self.tab_status = self.tabview.add("📊 상태")
        self.tab_manual = self.tabview.add("▶️ 실행")
        
        # 각 탭 구성
        self.setup_settings_tab()
        self.setup_status_tab()
        self.setup_manual_tab()
        
    def setup_settings_tab(self):
        """설정 탭 구성"""
        # Dauoffice 설정 프레임
        dauoffice_frame = ctk.CTkFrame(self.tab_settings)
        dauoffice_frame.pack(fill="x", padx=5, pady=5)  # 패딩 줄임
        
        ctk.CTkLabel(dauoffice_frame, text="📧 Dauoffice 설정", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=5, pady=3)  # 패딩 줄임
        
        # 아이디
        id_frame = ctk.CTkFrame(dauoffice_frame)
        id_frame.pack(fill="x", padx=5, pady=3)  # 패딩 줄임
        ctk.CTkLabel(id_frame, text="아이디:", width=100).pack(side="left", padx=5)
        self.dauoffice_id = ctk.CTkEntry(id_frame, width=200)
        self.dauoffice_id.pack(side="left", padx=5)
        
        # 비밀번호
        pw_frame = ctk.CTkFrame(dauoffice_frame)
        pw_frame.pack(fill="x", padx=5, pady=3)  # 패딩 줄임
        ctk.CTkLabel(pw_frame, text="비밀번호:", width=100).pack(side="left", padx=5)
        self.dauoffice_pw = ctk.CTkEntry(pw_frame, width=200, show="*")
        self.dauoffice_pw.pack(side="left", padx=5)
        
        # 대상 폴더
        folder_frame = ctk.CTkFrame(dauoffice_frame)
        folder_frame.pack(fill="x", padx=5, pady=3)  # 패딩 줄임
        ctk.CTkLabel(folder_frame, text="메일함 이름:", width=100).pack(side="left", padx=5)
        self.target_folder = ctk.CTkEntry(folder_frame, width=200)
        self.target_folder.pack(side="left", padx=5)
        
        # Gemini API 설정 프레임
        gemini_frame = ctk.CTkFrame(self.tab_settings)
        gemini_frame.pack(fill="x", padx=5, pady=5)  # 패딩 줄임
        
        ctk.CTkLabel(gemini_frame, text="🤖 Gemini AI 설정",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=5, pady=3)  # 패딩 줄임
        
        api_frame = ctk.CTkFrame(gemini_frame)
        api_frame.pack(fill="x", padx=5, pady=3)  # 패딩 줄임
        ctk.CTkLabel(api_frame, text="API Key:", width=100).pack(side="left", padx=5)
        self.gemini_api = ctk.CTkEntry(api_frame, width=300, show="*")
        self.gemini_api.pack(side="left", padx=5)
        
        ctk.CTkButton(api_frame, text="테스트", width=80,
                     command=self.test_gemini_api).pack(side="left", padx=5)
        
        # OpenAI API 설정 프레임
        openai_frame = ctk.CTkFrame(self.tab_settings)
        openai_frame.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(openai_frame, text="🔗 OpenAI API 설정 (선택사항)",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=5, pady=3)
        
        openai_api_frame = ctk.CTkFrame(openai_frame)
        openai_api_frame.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(openai_api_frame, text="API Key:", width=100).pack(side="left", padx=5)
        self.openai_api = ctk.CTkEntry(openai_api_frame, width=300, show="*")
        self.openai_api.pack(side="left", padx=5)
        
        ctk.CTkButton(openai_api_frame, text="테스트", width=80,
                     command=self.test_openai_api).pack(side="left", padx=5)
        
        # 결과 저장 설정 프레임
        output_frame = ctk.CTkFrame(self.tab_settings)
        output_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(output_frame, text="📁 결과 저장 설정",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        # 저장 경로
        path_frame = ctk.CTkFrame(output_frame)
        path_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(path_frame, text="저장 경로:", width=100).pack(side="left", padx=5)
        self.output_path = ctk.CTkEntry(path_frame, width=300)
        self.output_path.pack(side="left", padx=5)
        ctk.CTkButton(path_frame, text="찾아보기", width=80,
                     command=self.browse_folder).pack(side="left", padx=5)
        
        # 파일 형식
        format_frame = ctk.CTkFrame(output_frame)
        format_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(format_frame, text="파일 형식:", width=100).pack(side="left", padx=5)
        self.file_format = ctk.CTkSegmentedButton(format_frame, 
                                                  values=["Markdown (.md)", "텍스트 (.txt)"],
                                                  width=250)
        self.file_format.pack(side="left", padx=5)
        self.file_format.set("Markdown (.md)")
        
        # 도움말 추가
        help_label = ctk.CTkLabel(format_frame, text="ℹ️ Markdown: Obsidian 등 노트 앱 지원, 텍스트: 일반 텍스트 파일", 
                                 font=ctk.CTkFont(size=10), text_color="gray")
        help_label.pack(side="left", padx=10)
        
        # 스케줄 설정 프레임
        schedule_frame = ctk.CTkFrame(self.tab_settings)
        schedule_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(schedule_frame, text="⏰ 자동 실행 설정",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        time_frame = ctk.CTkFrame(schedule_frame)
        time_frame.pack(fill="x", padx=10, pady=5)
        
        self.schedule_enabled = ctk.CTkCheckBox(time_frame, text="자동 실행 활성화")
        self.schedule_enabled.pack(side="left", padx=5)
        
        ctk.CTkLabel(time_frame, text="실행 시간:").pack(side="left", padx=20)
        self.schedule_hour = ctk.CTkComboBox(time_frame, values=[f"{i:02d}" for i in range(24)], width=60)
        self.schedule_hour.pack(side="left", padx=5)
        ctk.CTkLabel(time_frame, text="시").pack(side="left")
        
        self.schedule_minute = ctk.CTkComboBox(time_frame, values=[f"{i:02d}" for i in range(0, 60, 10)], width=60)
        self.schedule_minute.pack(side="left", padx=5)
        ctk.CTkLabel(time_frame, text="분").pack(side="left")
        
        # 저장 버튼
        ctk.CTkButton(self.tab_settings, text="💾 설정 저장", 
                     command=self.save_settings,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=20)
    
    def setup_status_tab(self):
        """상태 탭 구성"""
        # 상태 정보 프레임
        status_frame = ctk.CTkFrame(self.tab_status)
        status_frame.pack(fill="both", expand=True, padx=5, pady=5)  # 패딩 줄임
        
        ctk.CTkLabel(status_frame, text="📊 시스템 상태",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=5, pady=5)  # 패딩 줄임
        
        # 상태 정보 텍스트박스 - 높이를 늘리고 패딩 줄임
        self.status_text = ctk.CTkTextbox(status_frame, height=450, font=ctk.CTkFont(size=12))
        self.status_text.pack(fill="both", expand=True, padx=5, pady=5)  # 패딩 줄임
        
        # 새로고침 버튼
        self.refresh_button = ctk.CTkButton(self.tab_status, text="🔄 상태 새로고침",
                                           command=self.update_status_with_animation)
        self.refresh_button.pack(pady=5)  # 패딩 줄임
        
        self.update_status()
    
    def setup_manual_tab(self):
        """수동 실행 탭 구성"""
        manual_frame = ctk.CTkFrame(self.tab_manual)
        manual_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(manual_frame, text="🚀 수동 실행",
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)  # 패딩 줄임
        
        # 실행 옵션
        options_frame = ctk.CTkFrame(manual_frame)
        options_frame.pack(pady=10)  # 패딩 줄임
        
        self.process_all = ctk.CTkCheckBox(options_frame, text="모든 메일 처리 (중복 포함)")
        self.process_all.pack(pady=5)
        
        self.test_mode = ctk.CTkCheckBox(options_frame, text="테스트 모드 (최대 5개만 처리)")
        self.test_mode.pack(pady=5)
        
        self.headless_mode = ctk.CTkCheckBox(options_frame, text="실행과정 관찰하기 (브라우저 열기)")
        self.headless_mode.pack(pady=5)
        self.headless_mode.select()  # 기본값으로 체크
        
        # 실행 버튼들
        buttons_frame = ctk.CTkFrame(manual_frame)
        buttons_frame.pack(pady=10)  # 패딩 줄임
        
        # 버튼들을 2x2 그리드로 배치하여 공간 절약
        # 첫 번째 행
        ctk.CTkButton(buttons_frame, text="▶️ 기본 실행",
                     command=self.run_manual,
                     width=160, height=35,
                     font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=5, pady=3)
        
        ctk.CTkButton(buttons_frame, text="📊 전체 메일 정리",
                     command=self.run_all_mails_summary,
                     width=160, height=35,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     fg_color="green", hover_color="darkgreen").grid(row=0, column=1, padx=5, pady=3)
        
        # 두 번째 행
        ctk.CTkButton(buttons_frame, text="📧 안 읽은 메일만",
                     command=self.run_unread_mails_only,
                     width=160, height=35,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     fg_color="orange", hover_color="darkorange").grid(row=1, column=0, padx=5, pady=3)
        
        self.stop_button = ctk.CTkButton(buttons_frame, text="⏹️ 중지",
                     command=self.stop_process,
                     width=160, height=35,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     fg_color="red", hover_color="darkred",
                     state="disabled")
        self.stop_button.grid(row=1, column=1, padx=5, pady=3)
        
        # 진행 상태
        self.progress_label = ctk.CTkLabel(manual_frame, text="대기 중...")
        self.progress_label.pack(pady=5)  # 패딩 줄임
        
        self.progress_bar = ctk.CTkProgressBar(manual_frame, width=400)
        self.progress_bar.pack(pady=5)  # 패딩 줄임
        self.progress_bar.set(0)
        
        # 로그 출력 - 높이를 늘리고 패딩 줄임
        self.log_text = ctk.CTkTextbox(manual_frame, height=250, font=ctk.CTkFont(size=10))
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)  # 패딩 줄임
    
    def browse_folder(self):
        """폴더 선택 다이얼로그"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_path.delete(0, 'end')
            self.output_path.insert(0, folder)
    
    def test_gemini_api(self):
        """Gemini API 연결 테스트"""
        api_key = self.gemini_api.get().strip()
        if not api_key:
            messagebox.showwarning("경고", "API Key를 입력해주세요.")
            return
        
        try:
            classifier = AIClassifier(api_key=api_key)
            if classifier.test_connection():
                messagebox.showinfo("성공", "Gemini API 연결 성공!")
            else:
                messagebox.showerror("실패", "Gemini API 연결 실패")
        except Exception as e:
            messagebox.showerror("오류", f"API 테스트 중 오류: {e}")
    
    def test_openai_api(self):
        """OpenAI API 연결 테스트"""
        api_key = self.openai_api.get().strip()
        if not api_key:
            messagebox.showwarning("경고", "API Key를 입력해주세요.")
            return
        
        try:
            # OpenAI API 키로 AIClassifier 테스트
            test_config = {
                "gemini": {"api_key": ""},
                "openai": {"api_key": api_key},
                "api": {"primary": "gemini", "fallback": "openai"}
            }
            classifier = AIClassifier(config_dict=test_config)
            
            if classifier.openai_client:
                messagebox.showinfo("성공", "OpenAI API 연결 성공!")
            else:
                messagebox.showerror("실패", "OpenAI API 연결 실패")
        except Exception as e:
            messagebox.showerror("오류", f"API 테스트 중 오류: {e}")
    
    def save_settings(self):
        """설정 저장"""
        try:
            # Dauoffice 설정
            username = self.dauoffice_id.get().strip()
            password = self.dauoffice_pw.get().strip()
            folder = self.target_folder.get().strip()
            
            self.config["dauoffice"]["username"] = username
            self.config["dauoffice"]["password"] = password
            self.config["dauoffice"]["target_folder"] = folder
            
            # Gemini 설정
            api_key = self.gemini_api.get().strip()
            self.config["gemini"]["api_key"] = api_key
            
            # OpenAI 설정
            openai_key = self.openai_api.get().strip()
            self.config["openai"]["api_key"] = openai_key
            
            # 출력 설정 (안전성 보장)
            if "output" not in self.config:
                self.config["output"] = {}
            
            output_path = self.output_path.get().strip()
            self.config["output"]["path"] = output_path
            # 파일 형식에서 확장자만 추출
            format_text = self.file_format.get()
            if "Markdown" in format_text or ".md" in format_text:
                self.config["output"]["file_format"] = ".md"
            else:
                self.config["output"]["file_format"] = ".txt"
            
            # 스케줄 설정
            self.config["schedule"]["enabled"] = self.schedule_enabled.get()
            self.config["schedule"]["time"] = f"{self.schedule_hour.get()}:{self.schedule_minute.get()}"
            
            # 설정 저장
            self.save_config()
            
            print(f"Debug: 저장된 설정 - ID: {username}, Folder: {folder}, API: {api_key[:10] if api_key else 'None'}...")  # 디버깅용
            
        except Exception as e:
            print(f"Debug: 설정 저장 오류: {e}")  # 디버꺅용
            raise e
        
        # 스케줄러 업데이트
        if self.config["schedule"]["enabled"]:
            self.scheduler.setup_schedule(
                self.config["schedule"]["time"],
                self.run_scheduled
            )
        else:
            self.scheduler.stop()
        
        messagebox.showinfo("성공", "설정이 저장되었습니다.")
        self.update_status()
    
    def load_settings(self):
        """설정 불러오기"""
        try:
            # 기존 값 클리어
            self.dauoffice_id.delete(0, 'end')
            self.dauoffice_pw.delete(0, 'end')
            self.target_folder.delete(0, 'end')
            self.gemini_api.delete(0, 'end')
            self.openai_api.delete(0, 'end')
            self.output_path.delete(0, 'end')
            
            # Dauoffice 설정
            self.dauoffice_id.insert(0, self.config["dauoffice"]["username"])
            self.dauoffice_pw.insert(0, self.config["dauoffice"]["password"])
            self.target_folder.insert(0, self.config["dauoffice"]["target_folder"])
            
            # Gemini 설정
            self.gemini_api.insert(0, self.config["gemini"]["api_key"])
            
            # OpenAI 설정
            self.openai_api.insert(0, self.config.get("openai", {}).get("api_key", ""))
            
            # 출력 설정
            self.output_path.insert(0, self.config.get("output", {}).get("path", ""))
            # 파일 형식 설정
            file_format = self.config.get("output", {}).get("file_format", ".md")
            if file_format == ".md":
                self.file_format.set("Markdown (.md)")
            else:
                self.file_format.set("텍스트 (.txt)")
            
            # 스케줄 설정
            if self.config["schedule"]["enabled"]:
                self.schedule_enabled.select()
            else:
                self.schedule_enabled.deselect()
                
            time_parts = self.config["schedule"]["time"].split(":")
            self.schedule_hour.set(time_parts[0])
            self.schedule_minute.set(time_parts[1] if len(time_parts) > 1 else "00")
            
            print(f"Debug: 로드된 설정 - ID: {self.config['dauoffice']['username']}, API: [암호화됨], Path: {self.config.get('output', {}).get('path', 'None')}")  # 디버깅용
            
        except Exception as e:
            print(f"Debug: 설정 로드 오류: {e}")  # 디버깅용
    
    def update_status_with_animation(self):
        """시각적 효과와 함께 상태 새로고침"""
        # 버튼 애니메이션 시작
        self.animate_refresh_button()
        
        # 상태창을 잠시 "새로고침 중..." 메시지로 변경
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", """
🔄🔄🔄 상태 새로고침 중... 🔄🔄🔄

    ██████╗ ███████╗███████╗██████╗ ███████╗███████╗██╗  ██╗
    ██╔══██╗██╔════╝██╔════╝██╔══██╗██╔════╝██╔════╝██║  ██║
    ██████╔╝█████╗  █████╗  ██████╔╝█████╗  ███████╗███████║
    ██╔══██╗██╔══╝  ██╔══╝  ██╔══██╗██╔══╝  ╚════██║██╔══██║
    ██║  ██║███████╗██║     ██║  ██║███████╗███████║██║  ██║
    ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝

                    잠시만 기다려 주세요...
        """)
        
        # 1초 후에 실제 상태 업데이트
        self.root.after(1000, self.update_status)
    
    def animate_refresh_button(self):
        """새로고침 버튼 애니메이션"""
        animations = [
            "🔄 새로고침 중.",
            "🔄 새로고침 중..",
            "🔄 새로고침 중...",
            "✨ 새로고침 중...✨",
            "🔄 상태 새로고침"
        ]
        
        def animate(step):
            if step < len(animations):
                self.refresh_button.configure(text=animations[step])
                self.root.after(200, lambda: animate(step + 1))
        
        animate(0)
    
    def update_status(self):
        """상태 정보 업데이트"""
        # 새로고침 시간 기록
        refresh_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 로그에도 새로고침 기록
        if hasattr(self, 'add_log'):
            self.add_log(f"🔄 상태 새로고침 실행됨 ({refresh_time})")
        
        status_info = []
        status_info.append("=" * 50)
        status_info.append("📊 시스템 상태")
        status_info.append("=" * 50)
        status_info.append("")
        
        # 새로고침 시간 표시
        status_info.append(f"🔄 마지막 새로고침: {refresh_time}")
        status_info.append("")
        status_info.append("")
        
        # 마지막 실행 시간
        if self.config.get("last_run"):
            status_info.append(f"⏱️ 마지막 실행: {self.config['last_run']}")
        else:
            status_info.append("⏱️ 마지막 실행: 없음")
        
        # 처리된 메일 수
        processed_count = len(self.config.get("processed_mails", []))
        status_info.append(f"📧 처리된 메일: {processed_count}개")
        
        # 웹메일요약 폴더 정보
        try:
            from pathlib import Path
            summary_dir = Path("웹메일요약")
            if summary_dir.exists():
                summary_files = list(summary_dir.glob("*.md"))
                today_file = summary_dir / f"메일요약_{datetime.now().strftime('%Y-%m-%d')}.md"
                status_info.append(f"📋 요약 보고서: {len(summary_files)}개")
                if today_file.exists():
                    status_info.append(f"   ✅ 오늘 보고서: 존재함")
                else:
                    status_info.append(f"   ⭕ 오늘 보고서: 없음")
            else:
                status_info.append("📋 요약 보고서: 폴더 없음")
        except Exception as e:
            status_info.append(f"📋 요약 보고서: 확인 실패 ({e})")
        
        # API 연결 상태 (더 정확한 체크)
        if self.config["gemini"]["api_key"]:
            try:
                # API 키가 있으면 연결 테스트 (간단히)
                api_key = self.config["gemini"]["api_key"]
                if len(api_key) > 30 and api_key.startswith("AIza"):
                    api_status = "✅ API 키 설정됨"
                else:
                    api_status = "⚠️ API 키 형식 의심스러움"
            except:
                api_status = "❓ API 키 상태 불명"
        else:
            api_status = "❌ API 키 미설정"
        status_info.append(f"🤖 Gemini API: {api_status}")
        
        # OpenAI API 상태
        openai_key = self.config.get("openai", {}).get("api_key", "")
        if openai_key:
            if len(openai_key) > 20 and openai_key.startswith("sk-"):
                openai_status = "✅ API 키 설정됨"
            else:
                openai_status = "⚠️ API 키 형식 의심스러움"
        else:
            openai_status = "❌ API 키 미설정 (선택사항)"
        status_info.append(f"🔗 OpenAI API: {openai_status}")
        
        # 스케줄 상태
        schedule_status = "✅ 활성화" if self.config["schedule"]["enabled"] else "❌ 비활성화"
        status_info.append(f"⏰ 자동 실행: {schedule_status}")
        if self.config["schedule"]["enabled"]:
            status_info.append(f"   📅 실행 시간: 매일 {self.config['schedule']['time']}")
        
        # 출력 경로 상태
        output_path = self.config.get("output", {}).get("path", "") or "미설정"
        if output_path != "미설정":
            from pathlib import Path
            if Path(output_path).exists():
                status_info.append(f"📁 저장 경로: ✅ {output_path}")
            else:
                status_info.append(f"📁 저장 경로: ❌ {output_path} (경로 없음)")
        else:
            status_info.append(f"📁 저장 경로: ❌ 미설정")
        
        # 파일 형식
        file_format = self.config.get("output", {}).get("file_format", ".md")
        status_info.append(f"📄 파일 형식: {file_format}")
        
        # Enhanced 파일 관리자 통계 (가능한 경우)
        try:
            if hasattr(self, 'file_manager'):
                stats = self.file_manager.get_processing_statistics()
                status_info.append(f"📊 처리된 메일: {stats['total_processed']}건")
                if stats['categories']:
                    top_category = max(stats['categories'].items(), key=lambda x: x[1])
                    status_info.append(f"   🏷️ 주요 주제: {top_category[0]} ({top_category[1]}건)")
                status_info.append(f"   📁 주제별 파일: {stats['files_structure']['topic_files']}개")
                status_info.append(f"   📅 날짜별 파일: {stats['files_structure']['daily_files']}개")
        except Exception as e:
            logger.debug(f"Enhanced 통계 로드 실패: {e}")
            pass
        
        # Dauoffice 설정 상태
        dauoffice_status = []
        if self.config.get("dauoffice", {}).get("username"):
            dauoffice_status.append("✅ 사용자명")
        else:
            dauoffice_status.append("❌ 사용자명")
            
        if self.config.get("dauoffice", {}).get("password"):
            dauoffice_status.append("✅ 비밀번호")
        else:
            dauoffice_status.append("❌ 비밀번호")
            
        if self.config.get("dauoffice", {}).get("target_folder"):
            dauoffice_status.append(f"✅ 폴더({self.config['dauoffice']['target_folder']})")
        else:
            dauoffice_status.append("❌ 대상 폴더")
        
        status_info.append("")
        status_info.append(f"🌐 Dauoffice 설정: {' | '.join(dauoffice_status)}")
        
        # 보안 상태 정보 추가
        status_info.append("")
        status_info.append("🔒 보안 상태")
        status_info.append("-" * 20)
        
        try:
            security_status = self.security_manager.verify_security()
            
            if security_status["encrypted_config_exists"]:
                status_info.append("✅ 암호화된 설정: 존재함")
            else:
                status_info.append("⚠️ 암호화된 설정: 없음")
            
            if security_status["key_file_exists"]:
                status_info.append("✅ 보안 키 파일: 존재함")
            else:
                status_info.append("⚠️ 보안 키 파일: 없음")
            
            if security_status["plaintext_sensitive_data"]:
                status_info.append("🚨 평문 민감정보: 발견됨 (즉시 암호화 필요)")
            else:
                status_info.append("✅ 평문 민감정보: 안전함")
            
            if security_status["recommendations"]:
                status_info.append("")
                status_info.append("📋 보안 권장사항:")
                for rec in security_status["recommendations"]:
                    status_info.append(f"   • {rec}")
            else:
                status_info.append("✅ 보안: 모든 검사 통과")
                
        except Exception as e:
            status_info.append(f"❌ 보안 상태 확인 실패: {e}")
        
        status_info.append("")
        status_info.append("-" * 50)
        status_info.append("✅ 상태 확인 완료")
        status_info.append(f"⏰ 업데이트 시각: {refresh_time}")
        status_info.append("-" * 50)
        
        # 텍스트박스 업데이트 (애니메이션 효과)
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", "\n".join(status_info))
        
        # 상태 새로고침 완료 알림
        if hasattr(self, 'progress_label'):
            original_text = self.progress_label.cget("text")
            
            # 완료 메시지 표시
            self.progress_label.configure(text=f"✅ 상태 새로고침 완료 ({refresh_time})")
            
            # 2초 후 원래 텍스트로 복원
            self.root.after(2000, lambda: self.progress_label.configure(text=original_text) if hasattr(self, 'progress_label') else None)
    
    def run_manual(self):
        """기본 수동 실행 - 설정에 따른 메일 처리"""
        # 설정 확인
        if not self.validate_settings():
            return
        
        # 현재 설정 상태 로그 출력
        process_all_mode = self.process_all.get() if hasattr(self, 'process_all') else True
        test_mode_enabled = self.test_mode.get() if hasattr(self, 'test_mode') else False
        
        if process_all_mode:
            self.add_log("🔄 기본 실행: 모든 메일 처리 모드")
        else:
            self.add_log("📬 기본 실행: 안 읽은 메일만 처리 모드")
            
        if test_mode_enabled:
            self.add_log("🧪 테스트 모드 활성화 (최대 5개 메일만 처리)")
        
        # 실행 상태 설정
        self.set_running_state(True)
        
        # 실행 스레드 시작
        thread = threading.Thread(target=self.process_mails)
        thread.daemon = True
        thread.start()
    
    def run_all_mails_summary(self):
        """전체 메일 한번에 정리 (읽은 메일, 읽지 않은 메일 모두 포함)"""
        # 설정 확인
        if not self.validate_settings():
            return
        
        self.add_log("📊 전체 메일 한번에 정리 시작...")
        self.add_log("⚠️ 모든 메일(읽은 메일 + 읽지 않은 메일)을 처리합니다.")
        
        # 강제로 모든 메일 처리 모드 설정
        self.process_all.select()  # 모든 메일 처리 체크
        self.test_mode.deselect()  # 테스트 모드 해제
        
        # 실행 상태 설정
        self.set_running_state(True)
        
        # 실행 스레드 시작
        thread = threading.Thread(target=self.process_all_mails_with_summary)
        thread.daemon = True
        thread.start()
    
    def run_unread_mails_only(self):
        """안 읽은 메일만 정리"""
        # 설정 확인
        if not self.validate_settings():
            return
        
        self.add_log("📧 안 읽은 메일만 정리 시작...")
        self.add_log("📬 오늘 기준으로 안 읽은 메일만 처리합니다.")
        
        # 안 읽은 메일만 처리 모드 설정
        self.process_all.deselect()  # 모든 메일 처리 해제
        self.test_mode.deselect()    # 테스트 모드 해제
        
        # 실행 상태 설정
        self.set_running_state(True)
        
        # 실행 스레드 시작
        thread = threading.Thread(target=self.process_unread_mails_only)
        thread.daemon = True
        thread.start()
    
    def run_scheduled(self):
        """스케줄 실행"""
        logger.info("스케줄된 작업 시작")
        self.process_mails()
    
    def stop_process(self):
        """진행 중인 프로세스 중지"""
        if self.is_running:
            self.stop_requested = True
            self.add_log("⏹️ 중지 요청됨. 즉시 중지합니다...")
            self.update_progress("중지 중...", None)
            
            # 브라우저 강제 종료
            try:
                if self.mail_collector:
                    # Playwright 브라우저가 있다면 종료
                    if hasattr(self.mail_collector, 'browser'):
                        import asyncio
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                # 이은 진행 중인 비동기 작업에서는 새로운 루프를 만들 수 없음
                                pass
                            else:
                                asyncio.run(self.mail_collector.browser.close())
                        except:
                            pass
                    self.mail_collector = None
            except Exception as e:
                self.add_log(f"⚠️ 브라우저 종료 오류: {e}")
            
            # 상태 즉시 업데이트
            self.is_running = False
            self._update_button_states()
            self.add_log("✅ 중지 완료")
    
    def set_running_state(self, running):
        """실행 상태 설정 및 버튼 상태 업데이트"""
        self.is_running = running
        self.stop_requested = False
        
        # 버튼 상태 업데이트 (UI 스레드에서 실행)
        self.root.after(0, self._update_button_states)
    
    def _update_button_states(self):
        """버튼 상태 업데이트 (UI 스레드용)"""
        if self.is_running:
            self.stop_button.configure(state="normal")
        else:
            self.stop_button.configure(state="disabled")
    
    def validate_settings(self):
        """설정 유효성 검사"""
        if not self.config["dauoffice"]["username"] or not self.config["dauoffice"]["password"]:
            messagebox.showerror("오류", "Dauoffice 계정 정보를 입력해주세요.")
            return False
        
        if not self.config["dauoffice"]["target_folder"]:
            messagebox.showerror("오류", "대상 메일함을 입력해주세요.")
            return False
        
        if not self.config["gemini"]["api_key"]:
            messagebox.showerror("오류", "Gemini API Key를 입력해주세요.")
            return False
        
        if not self.config["output"]["path"]:
            messagebox.showerror("오류", "결과 저장 경로를 설정해주세요.")
            return False
        
        return True
    
    def process_mails(self):
        """메일 처리 메인 프로세스"""
        try:
            self.update_progress("초기화 중...", 0)
            
            # 컴포넌트 초기화
            headless = not (hasattr(self, 'headless_mode') and self.headless_mode.get())
            self.mail_collector = MailCollector(
                self.config["dauoffice"]["username"],
                self.config["dauoffice"]["password"],
                self.config["dauoffice"]["target_folder"],
                headless=headless
            )
            
            # 복호화된 설정을 AIClassifier에 전달
            self.ai_classifier = AIClassifier(config_dict=self.config)
            
            # 기존 Obsidian 관리자와 새로운 Enhanced 파일 관리자 모두 초기화
            self.obsidian_manager = ObsidianManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            self.file_manager = EnhancedFileManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            
            # 1. 메일 수집
            self.update_progress("Dauoffice 로그인 중...", 0.1)
            
            # 실행 모드 결정: 아무것도 선택하지 않았으면 모든 메일 처리 모드
            process_all_mode = self.process_all.get() if hasattr(self, 'process_all') else True
            test_mode_enabled = self.test_mode.get() if hasattr(self, 'test_mode') else False
            
            # 둘 다 선택하지 않았으면 기본적으로 모든 메일 처리
            if not process_all_mode and not test_mode_enabled:
                process_all_mode = True
                self.add_log("실행 모드가 선택되지 않아 '모든 메일 처리' 모드로 실행합니다.")
            
            mails = self.mail_collector.collect_mails(
                process_all=process_all_mode,
                test_mode=test_mode_enabled,
                processed_mails=self.config.get("processed_mails", [])
            )
            
            if not mails:
                self.update_progress("처리할 메일이 없습니다.", 1.0)
                self.add_log("처리할 새 메일이 없습니다.")
                self.add_log("💡 팁: 메일함에 새 메일이 있는지 확인해보세요.")
                return
            
            self.add_log(f"📧 수집 완료: {len(mails)}개 메일 발견")
            self.add_log(f"🤖 AI 분석 및 동적 분류 시작...")
            self.add_log("")  # 빈 줄로 구분
            
            # 2. AI 분류 및 저장
            total = len(mails)
            classified_mails = []
            
            for idx, mail in enumerate(mails, 1):
                # 중지 요청 확인
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                    
                progress = 0.1 + (0.7 * idx / total)
                
                # 현재 처리 중인 메일 정보 표시
                subject = mail.get('subject', '제목 없음')
                sender = mail.get('sender', '발신자 불명')
                self.update_progress(f"메일 분류 중... ({idx}/{total})", progress)
                self.add_log(f"🔄 분석 중: {subject[:40]}..." + (f" (발신: {sender[:20]})" if sender != '발신자 불명' else ""))
                
                # 중지 요청 재확인 (AI 분석 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                
                # AI 분류
                self.add_log(f"   🤖 AI 분석 시작...")
                classification = self.ai_classifier.classify_mail(mail)
                self.add_log(f"   📋 분류 결과: {classification.get('category', '기타')}")
                
                # 중지 요청 재확인 (AI 분석 후)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx}/{total}개 멤일 처리 완룼")
                    break
                classified_mails.append((mail, classification))
                
                # Enhanced 파일 관리자로 저장 (새로운 방식 - 주제별 + 날짜별)
                # 중지 요청 재확인 (파일 저장 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 멤일 처리 완룼")
                    break
                
                self.add_log(f"   💾 파일 저장 중...")
                mail_id = mail.get('id', f"mail_{idx}")
                save_result = self.file_manager.save_mail_enhanced(mail, classification, mail_id)
                
                if save_result["status"] == "success":
                    # 저장된 파일 정보 표시
                    created_files = len(save_result.get("files_created", []))
                    self.add_log(f"   📁 저장 완료: {created_files}개 파일 생성/업데이트")
                    
                    # 기존 Obsidian 저장도 유지 (백워드 호환)
                    try:
                        self.obsidian_manager.save_mail(mail, classification)
                        self.add_log(f"   🔄 Obsidian 호환 저장 완료")
                    except Exception as e:
                        logger.warning(f"Obsidian 저장 실패: {e}")
                        self.add_log(f"   ⚠️ Obsidian 저장 실패: {str(e)[:30]}...")
                    
                    # 처리 완료 표시 - Enhanced에서 자체 관리하므로 기존 방식 유지
                    if mail.get('id') and mail['id'] not in self.config["processed_mails"]:
                        self.config["processed_mails"].append(mail['id'])
                        
                    # 동적 카테고리 정보 표시
                    recommendation = save_result.get("recommendation", {})
                    if recommendation.get("new_trend_detected"):
                        trend = recommendation.get("new_trend_suggestion")
                        self.add_log(f"   🔍 새로운 트렌드 감지: {trend}")
                    
                    if recommendation.get("confidence", 0) < 0.5:
                        self.add_log(f"   🤔 분류 신뢰도 낮음 ({recommendation.get('confidence', 0):.2f}) - 추가 학습 필요")
                    
                    # 카테고리 재편 정보 표시
                    if "reorganization_check" in save_result:
                        reorg = save_result["reorganization_check"]
                        if reorg.get("reorganized"):
                            actions = reorg.get("actions", [])
                            self.add_log(f"   🔄 카테고리 자동 재편 완료: {len(actions)}개 작업")
                            for action in actions[:2]:  # 최대 2개만 표시
                                self.add_log(f"      • {action}")
                        elif reorg.get("needs_reorganization"):
                            plan = reorg.get("plan", {})
                            low_freq = len(plan.get("low_frequency_categories", []))
                            if low_freq > 0:
                                self.add_log(f"   📊 카테고리 재편 필요: 저빈도 주제 {low_freq}개 감지")
                
                elif save_result["status"] == "skipped":
                    self.add_log(f"   ⏭️ 중복: 이미 처리된 메일입니다")
                    continue
                elif save_result["status"] == "error":
                    self.add_log(f"   ❌ 저장 실패: {save_result.get('error', '알 수 없는 오류')[:30]}...")
                    continue
                
                self.add_log(f"✅ 완료: {subject[:25]}... → {classification['category']}")
                self.add_log("")  # 빈 줄로 구분
            
            # 3. 요약 보고서 생성
            self.update_progress("요약 보고서 생성 중...", 0.85)
            try:
                # 사용자 설정 경로로 MailSummarizer 초기화
                if not self.mail_summarizer:
                    base_path = self.config["output"]["path"]
                    self.mail_summarizer = MailSummarizer(base_path)
                summary_file = self.mail_summarizer.create_summary_report(classified_mails)
                self.add_log(f"📋 요약 보고서 생성 완료: {summary_file}")
            except Exception as e:
                logger.warning(f"요약 보고서 생성 실패: {e}")
                self.add_log(f"⚠️ 요약 보고서 생성 실패: {e}")
            
            # 4. 완료 처리
            self.config["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_config()
            
            self.update_progress(f"완료! {total}개 메일 처리됨", 1.0)
            self.add_log(f"\n🎉 총 {total}개 메일 처리 완료!")
            
            # 상태 업데이트
            self.update_status()
            
        except Exception as e:
            logger.error(f"메일 처리 중 오류: {e}", exc_info=True)
            self.update_progress(f"오류 발생: {str(e)}", 0)
            self.add_log(f"❌ 오류: {str(e)}")
            messagebox.showerror("오류", f"처리 중 오류가 발생했습니다:\n{str(e)}")
        finally:
            # 중지되었는지 확인 후 상태 리셋
            if not self.stop_requested:
                self.set_running_state(False)
            else:
                # 중지된 경우 이미 stop_process에서 처리됨
                self.add_log("⏹️ 전체 멤일 처리가 중지되었습니다.")
    
    def process_all_mails_with_summary(self):
        """전체 메일을 처리하고 요약 보고서 생성"""
        try:
            self.update_progress("전체 메일 정리 초기화 중...", 0)
            
            # 컴포넌트 초기화
            headless = not (hasattr(self, 'headless_mode') and self.headless_mode.get())
            self.mail_collector = MailCollector(
                self.config["dauoffice"]["username"],
                self.config["dauoffice"]["password"], 
                self.config["dauoffice"]["target_folder"],
                headless=headless
            )
            
            # 복호화된 설정을 AIClassifier에 전달
            self.ai_classifier = AIClassifier(config_dict=self.config)
            
            # 기존 Obsidian 관리자와 새로운 Enhanced 파일 관리자 모두 초기화
            self.obsidian_manager = ObsidianManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            self.file_manager = EnhancedFileManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            
            # 메일 수집 (모든 메일)
            self.update_progress("전체 메일 수집 중 (읽은 메일 + 읽지 않은 메일)...", 0.1)
            
            mails = self.mail_collector.collect_mails(
                process_all=True,  # 강제로 모든 메일 처리
                test_mode=False,   # 테스트 모드 해제
                processed_mails=[]  # 중복 체크 무시
            )
            
            if not mails:
                self.update_progress("처리할 메일이 없습니다.", 1.0)
                self.add_log("처리할 메일이 없습니다.")
                return
            
            self.add_log(f"📊 전체 {len(mails)}개의 메일을 정리합니다.")
            
            # AI 분류 및 저장
            classified_mails = []
            total = len(mails)
            
            for idx, mail in enumerate(mails, 1):
                # 중지 요청 확인
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                    
                progress = 0.1 + (0.7 * idx / total)
                
                # 현재 처리 중인 메일 정보 표시
                subject = mail.get('subject', '제목 없음')
                sender = mail.get('sender', '발신자 불명')
                self.update_progress(f"전체 메일 처리 중... ({idx}/{total})", progress)
                self.add_log(f"🔄 분석 중: {subject[:40]}..." + (f" (발신: {sender[:20]})" if sender != '발신자 불명' else ""))
                
                # 중지 요청 재확인 (AI 분석 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                
                # AI 분류
                self.add_log(f"   🤖 AI 분석 및 요약 시작...")
                classification = self.ai_classifier.classify_mail(mail)
                self.add_log(f"   📋 분류 결과: {classification.get('category', '기타')}")
                
                # 중지 요청 재확인 (AI 분석 후)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx}/{total}개 메일 처리 완료")
                    break
                    
                classified_mails.append((mail, classification))
                
                # Enhanced 파일 관리자로 저장 (주제별 + 날짜별)
                # 중지 요청 재확인 (파일 저장 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                    
                self.add_log(f"   💾 파일 저장 중...")
                mail_id = mail.get('id', f"all_mail_{idx}")
                save_result = self.file_manager.save_mail_enhanced(mail, classification, mail_id)
                
                if save_result["status"] == "success":
                    created_files = len(save_result.get("files_created", []))
                    self.add_log(f"   📁 저장 완료: {created_files}개 파일 업데이트")
                    
                    # 기존 방식도 유지
                    try:
                        self.obsidian_manager.save_mail(mail, classification)
                        self.add_log(f"   🔄 Obsidian 호환 저장 완료")
                    except Exception as e:
                        logger.warning(f"Obsidian 저장 실패: {e}")
                        self.add_log(f"   ⚠️ Obsidian 저장 실패: {str(e)[:30]}...")
                elif save_result["status"] == "skipped":
                    self.add_log(f"   ⏭️ 중복: 이미 처리된 메일입니다")
                    continue
                elif save_result["status"] == "error":
                    self.add_log(f"   ❌ 저장 실패: {save_result.get('error', '알 수 없는 오류')[:30]}...")
                    continue
                
                self.add_log(f"✅ 완료: {subject[:25]}... → {classification['category']}")
                self.add_log("")  # 빈 줄로 구분
            
            # 전체 요약 보고서 생성
            self.update_progress("전체 멤일 요약 보고서 생성 중...", 0.85)
            try:
                # 사용자 설정 경로로 MailSummarizer 초기화
                if not self.mail_summarizer:
                    base_path = self.config["output"]["path"]
                    self.mail_summarizer = MailSummarizer(base_path)
                summary_file = self.mail_summarizer.create_summary_report(classified_mails)
                self.add_log(f"📋 전체 메일 요약 보고서 생성 완료: {summary_file}")
            except Exception as e:
                logger.warning(f"요약 보고서 생성 실패: {e}")
                self.add_log(f"⚠️ 요약 보고서 생성 실패: {e}")
            
            # 완료 처리
            self.config["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_config()
            
            self.update_progress(f"전체 메일 정리 완료! {total}개 메일 처리됨", 1.0)
            self.add_log(f"\n🎉 전체 {total}개 메일 정리 완료!")
            
            # 상태 업데이트
            self.update_status()
            
        except Exception as e:
            logger.error(f"전체 메일 정리 중 오류: {e}", exc_info=True)
            self.update_progress(f"오류 발생: {str(e)}", 0)
            self.add_log(f"❌ 오류: {str(e)}")
            messagebox.showerror("오류", f"전체 메일 정리 중 오류가 발생했습니다:\n{str(e)}")
        finally:
            # 중지되었는지 확인 후 상태 리셋
            if not self.stop_requested:
                self.set_running_state(False)
            else:
                # 중지된 경우 이미 stop_process에서 처리됨
                self.add_log("⏹️ 전체 멤일 처리가 중지되었습니다.")
    
    def process_unread_mails_only(self):
        """안 읽은 메일만 처리"""
        try:
            self.update_progress("안 읽은 메일 검색 초기화 중...", 0)
            
            # 컴포넌트 초기화
            headless = not (hasattr(self, 'headless_mode') and self.headless_mode.get())
            self.mail_collector = MailCollector(
                self.config["dauoffice"]["username"],
                self.config["dauoffice"]["password"],
                self.config["dauoffice"]["target_folder"], 
                headless=headless
            )
            
            # 복호화된 설정을 AIClassifier에 전달
            self.ai_classifier = AIClassifier(config_dict=self.config)
            
            # 기존 Obsidian 관리자와 새로운 Enhanced 파일 관리자 모두 초기화
            self.obsidian_manager = ObsidianManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            self.file_manager = EnhancedFileManager(
                self.config["output"]["path"],
                self.config["output"]["file_format"]
            )
            
            # 메일 수집 (안 읽은 메일만)
            self.update_progress("안 읽은 메일만 수집 중...", 0.1)
            
            # 기본적으로 안 읽은 메일만 가져오는 모드
            mails = self.mail_collector.collect_mails(
                process_all=False,  # 모든 메일 처리 해제
                test_mode=False,    # 테스트 모드 해제  
                processed_mails=self.config.get("processed_mails", [])
            )
            
            if not mails:
                self.update_progress("처리할 안 읽은 메일이 없습니다.", 1.0)
                self.add_log("📬 처리할 안 읽은 메일이 없습니다.")
                return
            
            self.add_log(f"📧 {len(mails)}개의 안 읽은 메일을 정리합니다.")
            
            # AI 분류 및 저장
            classified_mails = []
            total = len(mails)
            
            for idx, mail in enumerate(mails, 1):
                # 중지 요청 확인
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                    
                progress = 0.1 + (0.7 * idx / total)
                
                # 현재 처리 중인 메일 정보 표시
                subject = mail.get('subject', '제목 없음')
                sender = mail.get('sender', '발신자 불명')
                self.update_progress(f"안 읽은 메일 처리 중... ({idx}/{total})", progress)
                self.add_log(f"🔄 분석 중: {subject[:40]}..." + (f" (발신: {sender[:20]})" if sender != '발신자 불명' else ""))
                
                # 중지 요청 재확인 (AI 분석 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                
                # AI 분류
                self.add_log(f"   🤖 AI 분석 시작...")
                classification = self.ai_classifier.classify_mail(mail)
                self.add_log(f"   📋 분류 결과: {classification.get('category', '기타')}")
                
                # 중지 요청 재확인 (AI 분석 후)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx}/{total}개 멤일 처리 완룼")
                    break
                classified_mails.append((mail, classification))
                
                # Enhanced 파일 관리자로 저장 (주제별 + 날짜별)
                # 중지 요청 재확인 (파일 저장 전)
                if self.stop_requested:
                    self.add_log(f"⏹️ 중지됨. {idx-1}/{total}개 메일 처리 완료")
                    break
                    
                self.add_log(f"   💾 파일 저장 중...")
                mail_id = mail.get('id', f"unread_mail_{idx}")
                save_result = self.file_manager.save_mail_enhanced(mail, classification, mail_id)
                
                if save_result["status"] == "success":
                    created_files = len(save_result.get("files_created", []))
                    self.add_log(f"   📁 저장 완료: {created_files}개 파일 업데이트")
                    
                    # 기존 방식도 유지
                    try:
                        self.obsidian_manager.save_mail(mail, classification)
                        self.add_log(f"   🔄 Obsidian 호환 저장 완료")
                    except Exception as e:
                        logger.warning(f"Obsidian 저장 실패: {e}")
                        self.add_log(f"   ⚠️ Obsidian 저장 실패: {str(e)[:30]}...")
                        
                    # 처리 완료 표시
                    if mail.get('id') and mail['id'] not in self.config["processed_mails"]:
                        self.config["processed_mails"].append(mail['id'])
                        
                elif save_result["status"] == "skipped":
                    self.add_log(f"   ⏭️ 중복: 이미 처리된 메일입니다")
                    continue
                elif save_result["status"] == "error":
                    self.add_log(f"   ❌ 저장 실패: {save_result.get('error', '알 수 없는 오류')[:30]}...")
                    continue
                
                self.add_log(f"✅ 완료: {subject[:25]}... → {classification['category']}")
                self.add_log("")  # 빈 줄로 구분
            
            # 안 읽은 멤일 요약 보고서 생성
            self.update_progress("안 읽은 멤일 요약 보고서 생성 중...", 0.85)
            try:
                # 사용자 설정 경로로 MailSummarizer 초기화
                if not self.mail_summarizer:
                    base_path = self.config["output"]["path"]
                    self.mail_summarizer = MailSummarizer(base_path)
                summary_file = self.mail_summarizer.create_summary_report(classified_mails)
                self.add_log(f"📋 안 읽은 메일 요약 보고서 생성 완료: {summary_file}")
            except Exception as e:
                logger.warning(f"요약 보고서 생성 실패: {e}")
                self.add_log(f"⚠️ 요약 보고서 생성 실패: {e}")
            
            # 완료 처리
            self.config["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_config()
            
            self.update_progress(f"안 읽은 메일 정리 완료! {total}개 메일 처리됨", 1.0)
            self.add_log(f"\n🎉 안 읽은 {total}개 메일 정리 완료!")
            
            # 상태 업데이트
            self.update_status()
            
        except Exception as e:
            logger.error(f"안 읽은 메일 정리 중 오류: {e}", exc_info=True)
            self.update_progress(f"오류 발생: {str(e)}", 0)
            self.add_log(f"❌ 오류: {str(e)}")
            messagebox.showerror("오류", f"안 읽은 메일 정리 중 오류가 발생했습니다:\n{str(e)}")
        finally:
            # 중지되었는지 확인 후 상태 리셋
            if not self.stop_requested:
                self.set_running_state(False)
            else:
                # 중지된 경우 이미 stop_process에서 처리됨
                self.add_log("⏹️ 전체 멤일 처리가 중지되었습니다.")
    
    def update_progress(self, message, value):
        """진행 상태 업데이트"""
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(text=message)
        if hasattr(self, 'progress_bar') and value is not None:
            # value가 None이 아니고 유효한 범위일 때만 progress bar 업데이트
            if isinstance(value, (int, float)) and 0 <= value <= 1:
                self.progress_bar.set(value)
        self.root.update()
    
    def add_log(self, message):
        """로그 메시지 추가"""
        if hasattr(self, 'log_text'):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{timestamp}] {message}\n")
            self.log_text.see("end")
            self.root.update()
        logger.info(message)
    
    def run(self):
        """GUI 실행"""
        try:
            self.root.mainloop()
        except Exception as e:
            logger.error(f"GUI 실행 중 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            # GUI 오류가 발생해도 프로그램이 완전히 종료되지 않도록 함
            logger.info("GUI가 비정상 종료되었습니다.")