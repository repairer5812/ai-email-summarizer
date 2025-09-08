#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

class SecurityManager:
    """민감한 정보를 암호화하여 관리하는 보안 관리자"""
    
    def __init__(self, master_password=None):
        """
        보안 관리자 초기화
        Args:
            master_password: 마스터 비밀번호 (None이면 시스템 정보 기반으로 생성)
        """
        self.config_file = Path("config.json")
        self.secure_config_file = Path("config_secure.enc")
        self.key_file = Path(".security_key")
        
        # 마스터 키 생성/로드
        if master_password:
            self.master_key = self._generate_key_from_password(master_password)
        else:
            self.master_key = self._get_or_create_system_key()
        
        self.fernet = Fernet(self.master_key)
    
    def _generate_key_from_password(self, password: str) -> bytes:
        """비밀번호에서 암호화 키 생성"""
        password = password.encode()
        salt = b'webmail_security_salt_2024'  # 고정 솔트 (실제로는 랜덤 솔트 사용 권장)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def _get_or_create_system_key(self) -> bytes:
        """시스템 기반 키 생성/로드"""
        if self.key_file.exists():
            try:
                with open(self.key_file, 'rb') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"기존 키 파일 로드 실패: {e}")
        
        # 새 키 생성
        key = Fernet.generate_key()
        
        try:
            # 키 파일에 숨김 속성 설정 (Windows)
            with open(self.key_file, 'wb') as f:
                f.write(key)
            
            if os.name == 'nt':  # Windows
                os.system(f'attrib +h "{self.key_file}"')
            
            logger.info("새로운 보안 키가 생성되었습니다.")
            return key
            
        except Exception as e:
            logger.error(f"키 파일 생성 실패: {e}")
            # 메모리에만 저장
            return key
    
    def encrypt_config(self, config_data: dict) -> bool:
        """설정 데이터를 암호화하여 저장"""
        try:
            # 민감한 정보만 추출
            sensitive_data = self._extract_sensitive_data(config_data)
            
            if not sensitive_data:
                logger.warning("암호화할 민감한 정보가 없습니다.")
                return False
            
            # JSON으로 직렬화 후 암호화
            json_data = json.dumps(sensitive_data, ensure_ascii=False, indent=2)
            encrypted_data = self.fernet.encrypt(json_data.encode('utf-8'))
            
            # 암호화된 파일 저장
            with open(self.secure_config_file, 'wb') as f:
                f.write(encrypted_data)
            
            # 원본 설정에서 민감한 정보 제거
            safe_config = self._create_safe_config(config_data)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(safe_config, f, ensure_ascii=False, indent=2)
            
            logger.info("설정이 암호화되어 저장되었습니다.")
            return True
            
        except Exception as e:
            logger.error(f"설정 암호화 실패: {e}")
            return False
    
    def decrypt_config(self) -> dict:
        """암호화된 설정을 복호화하여 로드"""
        try:
            # 기본 설정 로드
            base_config = self._load_base_config()
            
            # 암호화된 파일이 있는지 확인
            if not self.secure_config_file.exists():
                logger.warning("암호화된 설정 파일이 없습니다. 기본 설정만 사용합니다.")
                return base_config
            
            # 암호화된 파일 읽기
            with open(self.secure_config_file, 'rb') as f:
                encrypted_data = f.read()
            
            # 복호화
            decrypted_data = self.fernet.decrypt(encrypted_data)
            sensitive_data = json.loads(decrypted_data.decode('utf-8'))
            
            logger.info(f"암호화된 설정 복호화됨: {len(sensitive_data)}개 민감 항목")
            
            # 기본 설정과 병합
            merged_config = self._merge_configs(base_config, sensitive_data)
            
            # 병합 결과 디버깅
            logger.info(f"병합 결과: password = {merged_config.get('dauoffice', {}).get('password', 'None')[:20]}...")
            
            return merged_config
            
        except Exception as e:
            logger.error(f"설정 복호화 실패: {e}")
            logger.info("기본 설정으로 폴백합니다.")
            return base_config if 'base_config' in locals() else self._load_base_config()
    
    def _extract_sensitive_data(self, config_data: dict) -> dict:
        """민감한 정보만 추출"""
        sensitive_data = {}
        
        # Dauoffice 비밀번호
        if config_data.get("dauoffice", {}).get("password"):
            sensitive_data["dauoffice_password"] = config_data["dauoffice"]["password"]
        
        # API 키들
        if config_data.get("gemini", {}).get("api_key"):
            sensitive_data["gemini_api_key"] = config_data["gemini"]["api_key"]
        
        if config_data.get("openai", {}).get("api_key"):
            sensitive_data["openai_api_key"] = config_data["openai"]["api_key"]
        
        return sensitive_data
    
    def _create_safe_config(self, config_data: dict) -> dict:
        """민감한 정보를 제거한 안전한 설정 생성"""
        safe_config = config_data.copy()
        
        # 민감한 정보를 플레이스홀더로 교체
        if "dauoffice" in safe_config:
            if safe_config["dauoffice"].get("password"):
                safe_config["dauoffice"]["password"] = "ENCRYPTED_PASSWORD"
        
        if "gemini" in safe_config:
            if safe_config["gemini"].get("api_key"):
                safe_config["gemini"]["api_key"] = "ENCRYPTED_API_KEY"
        
        if "openai" in safe_config:
            if safe_config["openai"].get("api_key"):
                safe_config["openai"]["api_key"] = "ENCRYPTED_API_KEY"
        
        return safe_config
    
    def _load_base_config(self) -> dict:
        """기본 설정 로드"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    base_config = json.load(f)
                    
                    # 디버깅: 로드된 설정 출력
                    logger.info(f"기본 설정 로드됨: dauoffice.password = {base_config.get('dauoffice', {}).get('password', 'None')[:20]}...")
                    return base_config
            except Exception as e:
                logger.error(f"기본 설정 로드 실패: {e}")
        
        # 기본 설정 구조
        return {
            "dauoffice": {"username": "", "password": "", "target_folder": ""},
            "gemini": {"api_key": ""},
            "openai": {"api_key": ""},
            "output": {"path": "", "file_format": ""},
            "api": {"primary": "gemini", "fallback": "openai"},
            "schedule": {"enabled": False, "time": "09:00"},
            "processed_mails": [],
            "last_run": ""
        }
    
    def _merge_configs(self, base_config: dict, sensitive_data: dict) -> dict:
        """기본 설정과 민감한 정보 병합"""
        merged_config = base_config.copy()
        
        # 민감한 정보 병합
        if "dauoffice_password" in sensitive_data:
            if "dauoffice" not in merged_config:
                merged_config["dauoffice"] = {}
            merged_config["dauoffice"]["password"] = sensitive_data["dauoffice_password"]
        
        if "gemini_api_key" in sensitive_data:
            if "gemini" not in merged_config:
                merged_config["gemini"] = {}
            merged_config["gemini"]["api_key"] = sensitive_data["gemini_api_key"]
        
        if "openai_api_key" in sensitive_data:
            if "openai" not in merged_config:
                merged_config["openai"] = {}
            merged_config["openai"]["api_key"] = sensitive_data["openai_api_key"]
        
        return merged_config
    
    def migrate_existing_config(self) -> bool:
        """기존의 평문 설정을 암호화된 설정으로 마이그레이션"""
        try:
            if not self.config_file.exists():
                logger.info("마이그레이션할 설정 파일이 없습니다.")
                return False
            
            # 기존 설정 로드
            with open(self.config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
            
            # 민감한 정보가 있는지 확인
            sensitive_info_found = (
                existing_config.get("dauoffice", {}).get("password", "") not in ["", "ENCRYPTED_PASSWORD"] or
                existing_config.get("gemini", {}).get("api_key", "") not in ["", "ENCRYPTED_API_KEY"] or
                existing_config.get("openai", {}).get("api_key", "") not in ["", "ENCRYPTED_API_KEY"]
            )
            
            if sensitive_info_found:
                logger.info("평문 민감 정보 발견. 암호화를 시작합니다...")
                
                # 기존 설정 백업
                backup_file = Path(f"{self.config_file}.backup")
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_config, f, ensure_ascii=False, indent=2)
                
                # 암호화
                success = self.encrypt_config(existing_config)
                if success:
                    logger.info(f"마이그레이션 완료. 백업 파일: {backup_file}")
                    return True
                else:
                    logger.error("마이그레이션 실패")
                    return False
            else:
                logger.info("이미 암호화된 설정입니다.")
                return True
                
        except Exception as e:
            logger.error(f"마이그레이션 중 오류: {e}")
            return False
    
    def verify_security(self) -> dict:
        """보안 상태 확인"""
        status = {
            "encrypted_config_exists": self.secure_config_file.exists(),
            "key_file_exists": self.key_file.exists(),
            "plaintext_sensitive_data": False,
            "recommendations": []
        }
        
        # 평문 민감 정보 확인
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                sensitive_in_plain = (
                    config.get("dauoffice", {}).get("password", "") not in ["", "ENCRYPTED_PASSWORD"] or
                    config.get("gemini", {}).get("api_key", "") not in ["", "ENCRYPTED_API_KEY"] or
                    config.get("openai", {}).get("api_key", "") not in ["", "ENCRYPTED_API_KEY"]
                )
                
                status["plaintext_sensitive_data"] = sensitive_in_plain
                
                if sensitive_in_plain:
                    status["recommendations"].append("민감한 정보가 평문으로 저장되어 있습니다. 즉시 암호화하세요.")
                
            except Exception as e:
                logger.error(f"설정 파일 보안 검사 실패: {e}")
        
        # 권장사항
        if not status["encrypted_config_exists"]:
            status["recommendations"].append("암호화된 설정 파일을 생성하세요.")
        
        if not status["key_file_exists"]:
            status["recommendations"].append("보안 키 파일이 없습니다.")
        
        return status