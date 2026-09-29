@echo off
setlocal
if "%~2"=="" (
  echo Usage: materialize_mcp_dataset.cmd ^<python-runtime.json^> ^<materialization-spec.json^> 1>&2
  exit /b 2
)
call "%~dp0run_python.cmd" -RuntimeFile "%~1" "%~dp0materialize_mcp_dataset.py" --spec-file "%~2"
exit /b %ERRORLEVEL%
