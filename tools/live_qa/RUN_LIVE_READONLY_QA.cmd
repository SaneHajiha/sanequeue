@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" sanequeue_live_qa.py
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3.11 sanequeue_live_qa.py
  ) else (
    python sanequeue_live_qa.py
  )
)
echo.
echo Diagnostic finished. The CMD window will stay open.
pause
