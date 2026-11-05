# Setup EXE only (requires existing dist\NcurityF5Tool\ from PyInstaller).
# No code signing. Run: scripts\build_installer_only.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$DistExe = Join-Path $Root "dist\NcurityF5Tool\NcurityF5Tool.exe"
if (-not (Test-Path -LiteralPath $DistExe)) {
    Write-Error "Missing $DistExe — run scripts\build_windows.ps1 first (or build_customer_release.cmd)."
}

function Get-AppVersion {
    $toml = Join-Path $Root "pyproject.toml"
    $line = Select-String -Path $toml -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value }
    return "0.1.0"
}

$AppVersion = Get-AppVersion
$Iscc = $null
foreach ($c in @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )) {
    if (Test-Path -LiteralPath $c) { $Iscc = $c; break }
}
if (-not $Iscc) {
    Write-Error "Inno Setup 6 not found. Install: winget install JRSoftware.InnoSetup"
}

$InstallerOut = Join-Path $env:TEMP "ncurity-f5tool-installer"
if (Test-Path -LiteralPath $InstallerOut) {
    Remove-Item -LiteralPath $InstallerOut -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallerOut | Out-Null
& $Iscc "/DMyAppVersion=$AppVersion" "/O$InstallerOut" (Join-Path $Root "packaging\NcurityF5Tool.iss")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$DistInstaller = Join-Path $Root "dist\installer"
New-Item -ItemType Directory -Force -Path $DistInstaller | Out-Null
Copy-Item -LiteralPath (Join-Path $InstallerOut "NcurityF5Tool-Setup-$AppVersion.exe") -Destination $DistInstaller -Force
$Setup = Join-Path $DistInstaller "NcurityF5Tool-Setup-$AppVersion.exe"
$hash = (Get-FileHash -LiteralPath $Setup -Algorithm SHA256).Hash
Write-Host ""
Write-Host "Installer: $Setup"
Write-Host "SHA256:    $hash"
