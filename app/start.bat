@echo off
setlocal EnableExtensions
rem ============================================================
rem  GSV.CPP one-click launcher (ASCII only, no BOM)
rem  Tuned for RTX 2060 6GB (Vulkan backend)
rem  Layout: engine\ models\ python\ frontend\ config\ docs\
rem ============================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

rem --- critical: disable Vulkan coopmat2 for AR precision ---
set GGML_VK_DISABLE_COOPMAT2=1

rem --- text sidecar data dirs ---
set PYTHONIOENCODING=utf-8
set GSV_G2PW_MODEL=%ROOT%\models\frontend\g2pw
set GSV_BERT_DIR=%ROOT%\models\frontend\bert_tokenizer
set GSV_FAST_LANGDETECT=%ROOT%\models\frontend\fast_langdetect
set NLTK_DATA=%ROOT%\models\nltk_data

rem --- tunable knobs (override in config\gsv.env) ---
set GSV_DEVICE=vulkan
set GSV_PORT=9880
set GSV_SIDECAR_PORT=9882
set GSV_THREADS=
set GSV_OPEN_GUI=0

if exist "%ROOT%\config\gsv.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\config\gsv.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)
set "THREADS_ARG="
if not "%GSV_THREADS%"=="" set "THREADS_ARG=--threads %GSV_THREADS%"

echo [gsv] starting text sidecar on :%GSV_SIDECAR_PORT%
start "gsv-sidecar" /min "%ROOT%\python\python.exe" "%ROOT%\frontend\text_sidecar.py" --host 127.0.0.1 --port %GSV_SIDECAR_PORT%

echo [gsv] waiting for sidecar (first run loads g2pW onnx ~20s)...
set /a _w=0
:waitside
ping -n 2 127.0.0.1 >nul
set /a _w+=1
powershell -NoProfile -Command "try{$null=Invoke-WebRequest -Uri 'http://127.0.0.1:%GSV_SIDECAR_PORT%/health' -UseBasicParsing -TimeoutSec 2; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto sideok
if %_w% geq 90 goto sidefail
goto waitside
:sidefail
echo [gsv] WARNING: sidecar not ready after 90s; launching engine anyway
goto launch
:sideok
echo [gsv] sidecar ready.

:launch
echo [gsv] starting engine backend=%GSV_DEVICE% port=%GSV_PORT%
start "gsv-engine" /min "%ROOT%\engine\gsv_server.exe" --models "%ROOT%\models" --device %GSV_DEVICE% --port %GSV_PORT% --sidecar 127.0.0.1:%GSV_SIDECAR_PORT% --allow-path "%ROOT%" %THREADS_ARG%

rem --- optional: auto-load a voice after engine is ready ---
if "%GSV_VOICE%"=="" goto novoice
echo [gsv] waiting for engine...
set /a _e=0
:waiteng
ping -n 2 127.0.0.1 >nul
set /a _e+=1
powershell -NoProfile -Command "try{$null=Invoke-WebRequest -Uri 'http://127.0.0.1:%GSV_PORT%/health' -UseBasicParsing -TimeoutSec 2; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto engok
if %_e% geq 90 goto engfail
goto waiteng
:engfail
echo [gsv] WARNING: engine not ready, skip voice load
goto novoice
:engok
echo [gsv] loading voice %GSV_VOICE%
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri 'http://127.0.0.1:%GSV_PORT%/set_gpt_weights?weights_path=%GSV_VOICE%' -UseBasicParsing -TimeoutSec 180).Content}catch{Write-Host ('voice load failed: '+$_.Exception.Message)}"
:novoice

echo.
echo [gsv] API    : http://127.0.0.1:%GSV_PORT%
echo [gsv] health : http://127.0.0.1:%GSV_PORT%/health
echo [gsv] stop   : close this window, then kill gsv_server.exe / python.exe
echo.
if /i "%GSV_OPEN_GUI%"=="1" start "" "%~dp0Start GAG.bat"
endlocal
