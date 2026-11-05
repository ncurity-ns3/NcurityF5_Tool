@echo off
setlocal EnableExtensions
pushd "%~dp0.."
if errorlevel 1 (
  echo error: cannot cd to project root
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1"
set EXITCODE=%ERRORLEVEL%
popd
if not "%EXITCODE%"=="0" (
  echo.
  echo run_tests failed with exit code %EXITCODE%
  echo if python is missing, run: scripts\setup_dev.cmd
)
exit /b %EXITCODE%
