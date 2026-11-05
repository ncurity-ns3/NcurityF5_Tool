@echo off
setlocal EnableExtensions
rem paths with "&" (e.g. Config & Rules) must use pushd and quoted echo

pushd "%~dp0.."
if errorlevel 1 (
  echo error: cannot cd to project root
  echo path may contain special characters — try scripts\run_gui.ps1
  pause
  exit /b 1
)

echo.
echo [f5tool] starting gui preview...
echo project: "%CD%"
echo.
set QT_LOGGING_RULES=qt.gui.edid=false;*.warning=false
set QT_LOGGING_TO_CONSOLE=0

if not exist ".venv\Scripts\python.exe" (
  echo error: .venv not found. run scripts\setup_dev.cmd first
  popd
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m app.gui.main
set EXITCODE=%ERRORLEVEL%

popd

if not "%EXITCODE%"=="0" (
  echo.
  echo gui exited with error code %EXITCODE%
  pause
  exit /b %EXITCODE%
)

echo.
echo gui closed normally.
endlocal
