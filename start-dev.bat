@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Check backend-dev-8002.err.log and frontend-dev-5173.out.log.
  pause
)
