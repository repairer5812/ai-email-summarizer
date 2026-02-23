@echo off
setlocal

REM One-click dev run script for Windows.
REM Uses PowerShell to create venv, install deps, and start the GUI.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_dev.ps1"

endlocal
