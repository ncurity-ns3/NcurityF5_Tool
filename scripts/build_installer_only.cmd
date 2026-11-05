@echo off
setlocal EnableExtensions
pushd "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer_only.ps1"
set EXITCODE=%ERRORLEVEL%
popd
if %EXITCODE% neq 0 pause
exit /b %EXITCODE%
