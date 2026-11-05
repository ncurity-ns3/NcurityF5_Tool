@echo off
setlocal EnableExtensions
REM Full customer build: portable ZIP + Inno Setup installer (if ISCC installed).
REM Code signing: set NCURITY_SIGN_PFX_PATH or NCURITY_SIGN_CERT_SHA1 before running.

pushd "%~dp0.."
if errorlevel 1 (
  echo error: cannot cd to project root
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" -Installer
set EXITCODE=%ERRORLEVEL%
popd
if %EXITCODE% neq 0 pause
exit /b %EXITCODE%
