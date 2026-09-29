@echo off
setlocal
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0run_python.ps1" %*
exit /b %ERRORLEVEL%
