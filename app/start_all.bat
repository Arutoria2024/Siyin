@echo off
setlocal EnableExtensions
rem ============================================================
rem  gsv-tts unified launcher
rem  Order: text sidecar (:9882) -> engine (:9880) -> gateway (:9881)
rem  Idempotent: whatever already listens on a port is adopted, never
rem  duplicated. Safe to run twice; second run just re-verifies.
rem  ASCII only / no BOM / CRLF.
rem ============================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "RUNDIR=%ROOT%\run"
set "OUTDIR=%ROOT%\out"
set "PY=%ROOT%\python\python.exe"
set "ENGINE_EXE=%ROOT%\engine\gsv_server.exe"
set "GW_PY=%ROOT%\services\gateway\gateway.py"
set "CFG=%ROOT%\services\config.json"
set "TMPF=%TEMP%\gsv_tok_%RANDOM%.txt"

if not exist "%RUNDIR%" mkdir "%RUNDIR%" >nul 2>&1
if not exist "%OUTDIR%" mkdir "%OUTDIR%" >nul 2>&1

if not exist "%PY%"         goto err_py
if not exist "%ENGINE_EXE%" goto err_exe
if not exist "%GW_PY%"      goto err_gw
if not exist "%CFG%"        goto err_cfg

rem ---- environment, identical to start.bat -------------------
set GGML_VK_DISABLE_COOPMAT2=1
set PYTHONIOENCODING=utf-8
set GSV_G2PW_MODEL=%ROOT%\models\frontend\g2pw
set GSV_BERT_DIR=%ROOT%\models\frontend\bert_tokenizer
set GSV_FAST_LANGDETECT=%ROOT%\models\frontend\fast_langdetect
set NLTK_DATA=%ROOT%\models\nltk_data
set GSV_DEVICE=vulkan
set GSV_PORT=9880
set GSV_SIDECAR_PORT=9882
set GSV_THREADS=
set GSV_OPEN_GUI=0
set GSV_VOICE=
if exist "%ROOT%\config\gsv.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\config\gsv.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)
set "THREADS_ARG="
if not "%GSV_THREADS%"=="" set "THREADS_ARG=--threads %GSV_THREADS%"

echo.
echo [start_all] gsv-tts unified start
echo [start_all] root   = %ROOT%
echo [start_all] device = %GSV_DEVICE%   engine :%GSV_PORT%   sidecar :%GSV_SIDECAR_PORT%

rem ============================================================
rem  1) text sidecar
rem ============================================================
call :getportpid %GSV_SIDECAR_PORT%
if defined PORT_PID goto sid_reuse
echo [start_all] starting text sidecar on :%GSV_SIDECAR_PORT% ...
start "gsv-sidecar" /min "%PY%" "%ROOT%\frontend\text_sidecar.py" --host 127.0.0.1 --port %GSV_SIDECAR_PORT%
call :grabpid %GSV_SIDECAR_PORT% 60
if not defined PORT_PID goto err_sid_port
goto sid_pid
:sid_reuse
echo [start_all] sidecar already listening on :%GSV_SIDECAR_PORT%  pid=%PORT_PID%  (reuse)
:sid_pid
>"%RUNDIR%\sidecar.pid" echo %PORT_PID%

set /a _n=0
:sid_loop
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%GSV_SIDECAR_PORT%/health',timeout=3)" >nul 2>&1
if not errorlevel 1 goto sid_ok
set /a _n+=1
if %_n% geq 90 goto err_sid_health
ping -n 2 127.0.0.1 >nul
goto sid_loop
:sid_ok
echo [start_all] sidecar ready  pid=%PORT_PID%

rem ============================================================
rem  2) engine
rem ============================================================
call :getportpid %GSV_PORT%
if defined PORT_PID goto eng_reuse
echo [start_all] starting engine backend=%GSV_DEVICE% port=%GSV_PORT% ...
start "gsv-engine" /min "%ENGINE_EXE%" --models "%ROOT%\models" --device %GSV_DEVICE% --port %GSV_PORT% --sidecar 127.0.0.1:%GSV_SIDECAR_PORT% --allow-path "%ROOT%" %THREADS_ARG%
call :grabpid %GSV_PORT% 90
if not defined PORT_PID goto err_eng_port
goto eng_pid
:eng_reuse
echo [start_all] engine already listening on :%GSV_PORT%  pid=%PORT_PID%  (reuse)
:eng_pid
>"%RUNDIR%\engine.pid" echo %PORT_PID%

set /a _n=0
:eng_loop
"%PY%" -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:%GSV_PORT%/health',timeout=3));raise SystemExit(0 if (d.get('ok') and d.get('engine')=='ready' and d.get('sidecar')) else 1)" >nul 2>&1
if not errorlevel 1 goto eng_ok
set /a _n+=1
if %_n% geq 90 goto err_eng_health
ping -n 2 127.0.0.1 >nul
goto eng_loop
:eng_ok
echo [start_all] engine ready  pid=%PORT_PID%

rem ---- make sure the wanted voice is loaded (skip when already) ----
if "%GSV_VOICE%"=="" goto voice_done
"%PY%" -c "import json,urllib.request;m=json.load(urllib.request.urlopen('http://127.0.0.1:%GSV_PORT%/models',timeout=5));raise SystemExit(0 if m.get('current')=='%GSV_VOICE%' else 1)" >nul 2>&1
if not errorlevel 1 goto voice_have
echo [start_all] loading voice %GSV_VOICE% (takes ~15s) ...
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%GSV_PORT%/set_gpt_weights?weights_path=%GSV_VOICE%',timeout=180).read()" >nul 2>&1
if errorlevel 1 goto voice_warn
echo [start_all] voice %GSV_VOICE% loaded
goto voice_done
:voice_have
echo [start_all] voice %GSV_VOICE% already loaded
goto voice_done
:voice_warn
echo [start_all] WARNING: voice load call failed; engine keeps its current voice
:voice_done

rem ============================================================
rem  3) gateway
rem ============================================================
set "GW_PORT=9881"
set "TOKEN="
"%PY%" -c "import json;print(json.load(open(r'%CFG%','r',encoding='utf-8')).get('gateway',{}).get('token','') or '')" > "%TMPF%" 2>nul
if exist "%TMPF%" set /p TOKEN=<"%TMPF%"
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
if defined TOKEN goto tok_ok
echo [start_all] WARNING: gateway.token is empty, gateway runs WITHOUT auth
goto tok_done
:tok_ok
echo [start_all] gateway token read from services\config.json
:tok_done

call :getportpid %GW_PORT%
if defined PORT_PID goto gw_reuse
echo [start_all] starting gateway on :%GW_PORT% ...
start "gsv-gateway" /min "%PY%" "%GW_PY%" --config "%CFG%"
call :grabpid %GW_PORT% 90
if not defined PORT_PID goto err_gw_port
goto gw_pid
:gw_reuse
echo [start_all] gateway already listening on :%GW_PORT%  pid=%PORT_PID%  (reuse)
:gw_pid
>"%RUNDIR%\gateway.pid" echo %PORT_PID%

set /a _n=0
:gw_loop
if not defined TOKEN goto gw_probe_noauth
"%PY%" -c "import json,urllib.request;r=urllib.request.Request('http://127.0.0.1:%GW_PORT%/v1/health',headers={'Authorization':'Bearer %TOKEN%'});d=json.load(urllib.request.urlopen(r,timeout=5));raise SystemExit(0 if d.get('ok') else 1)" >nul 2>&1
goto gw_check
:gw_probe_noauth
"%PY%" -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:%GW_PORT%/v1/health',timeout=5));raise SystemExit(0 if d.get('ok') else 1)" >nul 2>&1
:gw_check
if not errorlevel 1 goto gw_ok
set /a _n+=1
if %_n% geq 90 goto err_gw_health
ping -n 2 127.0.0.1 >nul
goto gw_loop
:gw_ok
echo [start_all] gateway ready  pid=%PORT_PID%

rem ============================================================
echo.
echo ============================================================
echo  ALL READY
echo ============================================================
echo  engine  : http://127.0.0.1:%GSV_PORT%
echo  sidecar : http://127.0.0.1:%GSV_SIDECAR_PORT%
echo  gateway : http://127.0.0.1:%GW_PORT%
echo  health  : http://127.0.0.1:%GW_PORT%/v1/health
echo  LAN     : http://^<this-pc-ip^>:%GW_PORT%   token in services\config.json
echo  pids    : run\engine.pid  run\sidecar.pid  run\gateway.pid
echo  stop    : stop_all.bat
echo ============================================================
echo.
endlocal
exit /b 0

rem ------------------------------------------------------------
rem :getportpid <port>  -> PORT_PID = owning pid, empty when free
rem ------------------------------------------------------------
:getportpid
set "PORT_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr /C:"LISTENING"') do (
  if not defined PORT_PID set "PORT_PID=%%a"
)
goto :eof

rem ------------------------------------------------------------
rem :grabpid <port> <seconds>  -> poll until something listens
rem ------------------------------------------------------------
:grabpid
set /a _g=0
:grab_loop
call :getportpid %~1
if defined PORT_PID goto :eof
set /a _g+=1
if %_g% geq %~2 goto :eof
ping -n 2 127.0.0.1 >nul
goto grab_loop

rem ------------------------------------------------------------
rem  errors
rem ------------------------------------------------------------
:err_py
echo [start_all] ERROR: embedded python missing: %PY%
exit /b 1
:err_exe
echo [start_all] ERROR: engine missing: %ENGINE_EXE%
exit /b 1
:err_gw
echo [start_all] ERROR: gateway missing: %GW_PY%
exit /b 1
:err_cfg
echo [start_all] ERROR: config missing: %CFG%
exit /b 1
:err_sid_port
echo [start_all] ERROR: sidecar did not open :%GSV_SIDECAR_PORT% within 60s
exit /b 1
:err_sid_health
echo [start_all] ERROR: sidecar /health not ready after 90s
exit /b 1
:err_eng_port
echo [start_all] ERROR: engine did not open :%GSV_PORT% within 90s
exit /b 1
:err_eng_health
echo [start_all] ERROR: engine /health not ready after 90s
exit /b 1
:err_gw_port
echo [start_all] ERROR: gateway did not open :%GW_PORT% within 90s
exit /b 1
:err_gw_health
echo [start_all] ERROR: gateway /v1/health not ok after 90s
exit /b 1
