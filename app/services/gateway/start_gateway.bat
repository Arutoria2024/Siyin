@echo off
setlocal EnableExtensions
rem ============================================================
rem  gsv-tts LAN gateway (service B)  --  HTTP 0.0.0.0:9881
rem  Requires the engine to be running already (<PROJECT_ROOT>\start.bat)
rem  ASCII only, no BOM.
rem ============================================================
cd /d "%~dp0"
set "SVC=%~dp0"
if "%SVC:~-1%"=="\" set "SVC=%SVC:~0,-1%"
set "ROOT=%SVC%\.."
set "PY=%ROOT%\python\python.exe"
set "LOG=%SVC%\logs"

if not exist "%LOG%" mkdir "%LOG%"
if not exist "%PY%" (
  echo [fatal] python not found: %PY%
  exit /b 1
)

rem --- token: config.json wins, env is the fallback -------------------
if not "%GSV_TTS_TOKEN%"=="" echo [gateway] using token from GSV_TTS_TOKEN

echo [gateway] starting on port 9881 ...
echo [gateway] logs: %LOG%
"%PY%" "%SVC%\gateway.py" --config "%ROOT%\config.json" %*
set "RC=%ERRORLEVEL%"
echo [gateway] exited with code %RC%
if "%RC%"=="0" goto :eof
pause
