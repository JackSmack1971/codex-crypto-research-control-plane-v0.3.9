@echo off
setlocal
if "%~1"=="" (
  echo Usage: run_tests.cmd ^<python-runtime.json^> [test args...] 1>&2
  exit /b 2
)
set "RUNTIME=%~1"
shift
call "%~dp0run_python.cmd" -RuntimeFile "%RUNTIME%" "%~dp0run_tests.py" %*
exit /b %ERRORLEVEL%
