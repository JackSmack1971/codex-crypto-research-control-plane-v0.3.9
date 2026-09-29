@echo off
setlocal
if "%~1"=="" (
  echo Usage: validate_control_plane.cmd ^<python-runtime.json^> [validator args...] 1>&2
  exit /b 2
)
set "RUNTIME=%~1"
shift
call "%~dp0run_python.cmd" -RuntimeFile "%RUNTIME%" "%~dp0validate_control_plane.py" %*
exit /b %ERRORLEVEL%
