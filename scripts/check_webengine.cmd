@echo off
setlocal EnableExtensions
pushd "%~dp0.."
".venv\Scripts\python.exe" scripts\check_webengine.py
set EXITCODE=%ERRORLEVEL%
popd
pause
exit /b %EXITCODE%
