@echo off
setlocal
cd /d "%~dp0"

echo Starting DZMM web bot in debug mode...
echo Logs are also written to data\logs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1"
echo.
echo If the manager page did not open, check:
echo data\logs\startup.log
echo data\logs\service-error.log
pause
