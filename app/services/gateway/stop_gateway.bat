@echo off
setlocal EnableExtensions
rem Stop the gsv-tts gateway by killing whatever listens on port 9881.
rem ASCII only, no BOM.
set "PORT=9881"
if not "%~1"=="" set "PORT=%~1"

set "PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r ":%PORT% .*LISTENING"') do set "PID=%%p"
if "%PID%"=="" (
  echo [stop] nothing is listening on port %PORT%
  exit /b 0
)
echo [stop] killing pid %PID% on port %PORT%
taskkill /f /pid %PID% >nul 2>&1
if errorlevel 1 (
  echo [stop] taskkill failed for pid %PID%
  exit /b 1
)
echo [stop] done
