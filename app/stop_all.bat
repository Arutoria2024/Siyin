@echo off
setlocal EnableExtensions
rem ============================================================
rem  gsv-tts unified stopper
rem  Kills ONLY the pids recorded in run\*.pid, and only after the
rem  recorded process's command line still points at gsv-tts. Never a
rem  blind "taskkill /IM python.exe": other python services live here.
rem  ASCII only / no BOM / CRLF.
rem ============================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "RUNDIR=%ROOT%\run"
set "TMPF=%TEMP%\gsv_stop_%RANDOM%.txt"

echo.
echo [stop_all] gsv-tts unified stop
echo [stop_all] root = %ROOT%

set "KILLED=0"
set "SKIPPED=0"

if exist "%RUNDIR%\gateway.pid" call :stopone gateway "%RUNDIR%\gateway.pid" "gateway.py"
if exist "%RUNDIR%\engine.pid"  call :stopone engine  "%RUNDIR%\engine.pid"  "gsv_server"
if exist "%RUNDIR%\sidecar.pid" call :stopone sidecar "%RUNDIR%\sidecar.pid" "text_sidecar"

rem ---- fallback: gsv_server.exe is ours, a name kill is safe ----
tasklist /FI "IMAGENAME eq gsv_server.exe" /NH 2>nul | findstr /I "gsv_server.exe" >nul 2>&1
if errorlevel 1 goto fb_done
echo [stop_all] fallback: taskkill /IM gsv_server.exe /F
taskkill /IM gsv_server.exe /F >nul 2>&1
set "KILLED=1"
:fb_done

rem ---- port sweep: anything still listening on our ports that really is a
rem      gsv-tts process gets killed by pid (guards stale pid files).
call :sweepport 9881
call :sweepport 9880
call :sweepport 9882

rem ---- pid files out of the way ----
for %%f in (gateway engine sidecar) do (
  if exist "%RUNDIR%\%%f.pid" del "%RUNDIR%\%%f.pid" >nul 2>&1
)

rem ---- wait for ports to be released (max 20s) ----
set /a _w=0
:rel_loop
call :portsfree
if not errorlevel 1 goto rel_ok
set /a _w+=1
if %_w% geq 20 goto rel_timeout
ping -n 2 127.0.0.1 >nul
goto rel_loop
:rel_timeout
echo [stop_all] WARNING: ports still busy after 20s:
call :portreport
goto rel_done
:rel_ok
echo [stop_all] ports 9880 / 9881 / 9882 released
:rel_done

echo.
echo ============================================================
echo  ALL STOPPED
echo ============================================================
echo  killed=%KILLED%  skipped=%SKIPPED%
echo  pid files removed from run\
echo  start again with start_all.bat
echo ============================================================
echo.
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
endlocal
exit /b 0

rem ------------------------------------------------------------
rem :stopone <label> <pidfile> <cmdline-must-contain>
rem ------------------------------------------------------------
:stopone
set "LABEL=%~1"
set "PIDFILE=%~2"
set "NEEDLE=%~3"
set "PIDV="
set /p PIDV=<"%PIDFILE%"
if not defined PIDV goto so_done
for /f "tokens=* delims= " %%v in ("%PIDV%") do set "PIDV=%%v"
if not defined PIDV goto so_done

tasklist /FI "PID eq %PIDV%" /NH 2>nul | findstr /R "[0-9]" >nul 2>&1
if errorlevel 1 (
  echo [stop_all] %LABEL%  pid %PIDV%  already gone ^(skip^)
  goto so_done
)

rem -- verify identity before pulling the trigger --
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
powershell -NoProfile -Command "try{(Get-CimInstance Win32_Process -Filter 'ProcessId=%PIDV%' -ErrorAction Stop).CommandLine}catch{''}" > "%TMPF%" 2>nul
set "CMDLINE="
if exist "%TMPF%" set /p CMDLINE=<"%TMPF%"
if not defined CMDLINE (
  echo [stop_all] %LABEL%  pid %PIDV%  command line unreadable ^(skip^)
  goto so_done
)
echo %CMDLINE% | findstr /I /C:"%NEEDLE%" >nul 2>&1
if errorlevel 1 (
  echo [stop_all] %LABEL%  pid %PIDV%  not a gsv-tts process ^(skip: %CMDLINE%^)
  set /a SKIPPED+=1
  goto so_done
)

echo [stop_all] %LABEL%  pid %PIDV%  killing ...
taskkill /PID %PIDV% /F >nul 2>&1
if errorlevel 1 (
  echo [stop_all] %LABEL%  pid %PIDV%  taskkill refused ^(skip^)
  set /a SKIPPED+=1
  goto so_done
)
echo [stop_all] %LABEL%  pid %PIDV%  stopped
set "KILLED=1"
:so_done
goto :eof

rem ------------------------------------------------------------
rem :portsfree  -> errorlevel 1 when any of 9880/9881/9882 listens
rem ------------------------------------------------------------
:portsfree
netstat -ano | findstr /C:":9880 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 1
netstat -ano | findstr /C:":9881 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 1
netstat -ano | findstr /C:":9882 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 1
exit /b 0

:portreport
netstat -ano | findstr /C:":9880 " | findstr /C:"LISTENING"
netstat -ano | findstr /C:":9881 " | findstr /C:"LISTENING"
netstat -ano | findstr /C:":9882 " | findstr /C:"LISTENING"
goto :eof

rem ------------------------------------------------------------
rem :sweepport <port>  kill owner only if its cmdline is gsv-tts
rem ------------------------------------------------------------
:sweepport
set "SP="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr /C:"LISTENING"') do (
  if not defined SP set "SP=%%a"
)
if not defined SP goto :eof
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
powershell -NoProfile -Command "try{(Get-CimInstance Win32_Process -Filter 'ProcessId=%SP%' -ErrorAction Stop).CommandLine}catch{''}" > "%TMPF%" 2>nul
set "SCM="
if exist "%TMPF%" set /p SCM=<"%TMPF%"
if not defined SCM goto :eof
echo %SCM% | findstr /I /C:"gsv-tts" >nul 2>&1
if errorlevel 1 goto :eof
echo [stop_all] port %~1 still held by pid %SP% ^(gsv-tts^) - killing
taskkill /PID %SP% /F >nul 2>&1
set "KILLED=1"
goto :eof
