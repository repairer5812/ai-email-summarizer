#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

def get_app_directory():
    """
    애플리케이션의 기본 디렉토리를 반환합니다.
    다양한 실행 방법에 대응합니다.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller로 패키징된 경우
        return os.path.dirname(sys.executable)
    else:
        # 일반 Python 스크립트로 실행된 경우
        return os.path.dirname(os.path.abspath(__file__))

def ensure_app_directory():
    """
    애플리케이션 디렉토리로 작업 디렉토리를 변경합니다.
    """
    app_dir = get_app_directory()
    os.chdir(app_dir)
    return app_dir

def get_config_path():
    """
    설정 파일의 절대 경로를 반환합니다.
    """
    app_dir = get_app_directory()
    return os.path.join(app_dir, "config.json")

def get_logs_directory():
    """
    로그 디렉토리 경로를 반환하고, 없으면 생성합니다.
    """
    app_dir = get_app_directory()
    logs_dir = os.path.join(app_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

def check_environment():
    """
    실행 환경을 확인하고 필요한 디렉토리를 생성합니다.
    """
    app_dir = ensure_app_directory()
    logs_dir = get_logs_directory()
    
    print(f"🗂️  앱 디렉토리: {app_dir}")
    print(f"📁 설정 파일: {get_config_path()}")
    print(f"📝 로그 디렉토리: {logs_dir}")
    
    return {
        'app_dir': app_dir,
        'config_path': get_config_path(),
        'logs_dir': logs_dir
    }