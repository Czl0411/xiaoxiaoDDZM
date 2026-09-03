@echo off
setlocal
cd /d "%~dp0"

if not exist "main.py" (
  echo Start failed: please extract the zip package first.
  echo Do not run start.bat inside the compressed zip preview window.
  echo Current folder: %cd%
  pause
  exit /b 1
)

where powershell >nul 2>nul
if errorlevel 1 (
  echo Start failed: PowerShell was not found on this computer.
  pause
  exit /b 1
)

if not exist "runtime\python\python.exe" (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  )
  if errorlevel 1 (
    echo Start failed: Python 3.11+ was not found, and bundled Python is missing.
    echo Please use dzmm-web-bot-with-python.zip, or install Python 3.11+.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_hidden.ps1"

timeout /t 5 /nobreak >nul
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:7902/api/status' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo Start failed: the service did not start.
  echo Run start_debug.bat to see details, or check these files:
  echo data\logs\startup.log
  echo data\logs\service-error.log
  pause
  exit /b 1
)

exit /b 0
