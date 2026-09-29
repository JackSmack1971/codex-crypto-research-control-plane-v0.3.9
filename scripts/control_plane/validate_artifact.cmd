@echo off
setlocal
if "%~3"=="" (
  echo Usage: validate_artifact.cmd ^<python-runtime.json^> ^<artifact.json^> ^<schema.json^> 1>&2
  exit /b 2
)
call "%~dp0run_python.cmd" -RuntimeFile "%~1" "%~dp0validate_artifact.py" "%~2" "%~3"
exit /b %ERRORLEVEL%
