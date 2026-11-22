@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Use the portable release, or install Python 3.10+ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
echo Starting Claude Environment Sentinel local control console...
echo Loopback-only, local writes require confirmation. Press Ctrl+C to stop.
"%PY%" -m sentinel web-preview --port 8790 --open
if errorlevel 1 pause
endlocal
