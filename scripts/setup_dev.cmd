@echo off
setlocal EnableExtensions
pushd "%~dp0.."
if errorlevel 1 (
  echo error: cannot cd to project root
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_dev.ps1"
set EXITCODE=%ERRORLEVEL%
popd
exit /b %EXITCODE%
