# MSI only (requires existing dist\NcurityF5Tool\ from PyInstaller).
# The installed program remains NcurityF5Tool.exe.

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build_msi.ps1")
exit $LASTEXITCODE
