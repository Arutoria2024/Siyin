@echo off
rem Zero-window launcher: hands off to start_monitor.vbs which uses
rem WScript.Shell.Run with window style 0. This bat exits immediately.
cd /d "%~dp0"
if exist "%~dp0start_monitor.vbs" (
    start "" wscript.exe //nologo "%~dp0start_monitor.vbs"
    exit /b 0
)
rem Fallback (no vbs present): pythonw has no console of its own.
start "" "%~dp0python\pythonw.exe" "%~dp0monitor\monitor.py"
exit /b 0
