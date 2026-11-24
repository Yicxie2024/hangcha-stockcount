@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import win32com.client" >nul 2>&1
if errorlevel 1 (
  echo Installing required pywin32 for Microsoft Excel automation...
  py -3 -m pip install pywin32
  if errorlevel 1 goto fail
)
py -3 stockcount.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo Startup failed. Install Python 3.10+ and Microsoft Excel, then retry.
pause
