@echo off
rem Thin wrapper so every service can be started from one folder.
rem Delegates to the engine launcher shipped with the deployment.
cd /d "%~dp0"
set "ROOT=%~dp0.."
call "%ROOT%\start.bat"
