@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 merge_manager.py
if errorlevel 1 (
  echo Startup failed. Please install Python 3.10+ with Tkinter.
  pause
)
