@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "SANEQUEUE_DEMO_PORT=18895"
if not exist "logs" mkdir "logs"
echo.
echo ================================================================
echo   SaneQueue 2.1.0-beta.17 - FULL MENU RESTORATION / CALL JOURNEY BUILD
echo   Correct URL: http://127.0.0.1:18895/operations
echo   Build check: http://127.0.0.1:18895/__sanequeue__/build
echo   Older local SaneQueue versions remain untouched.
echo ================================================================
echo.
if not exist ".venv\Scripts\python.exe" (
   echo [1/3] Creating Python 3.11 virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 goto failed_venv
)
echo [2/3] Checking dependencies ...
if not exist ".venv\sanequeue_beta17_ready.flag" (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -r "requirements\modern.txt" > "logs\pip_install.log" 2>&1
  if errorlevel 1 goto failed_pip
  echo v2.1.0-beta.17 > ".venv\sanequeue_beta17_ready.flag"
) else (
  echo [OK] Previously installed dependencies detected.
)

echo [3/3] Starting server with visible diagnostics...
echo   Do not close this window while using the panel.
echo.
".venv\Scripts\python.exe" -u "START_DIAGNOSTIC.py"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo [INFO] Server stopped with exit code %EXITCODE%.
goto ending
:failed_venv
echo [ERROR] Python 3.11 could not be started. Install Python 3.11 or enable the Python Launcher.
goto ending
:failed_pip
echo [ERROR] Dependency installation failed; last lines:
powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\pip_install.log' -Tail 35" 
echo Full pip log: logs\pip_install.log
goto ending
:ending
echo.
echo If the panel does not open, please send logs\startup_last.log
echo No AMI passwords are needed for startup debugging.
pause
endlocal
