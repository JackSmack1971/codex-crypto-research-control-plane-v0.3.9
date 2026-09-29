@echo off
setlocal
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0search_repo.ps1" %*
exit /b %ERRORLEVEL%
