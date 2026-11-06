# Build Windows customer release: PyInstaller one-folder + ZIP + optional Inno Setup installer.
# Prerequisites: .venv with gui + pyinstaller + branding icons.
#
# Usage:
#   scripts\build_windows.ps1
#   scripts\build_windows.ps1 -Installer
#   scripts\build_windows.ps1 -SkipSign   # skip Authenticode even if env vars set
#
# Signing (recommended for EDR): set NCURITY_SIGN_PFX_PATH or NCURITY_SIGN_CERT_SHA1
#   then run without -SkipSign. See docs\customer_delivery.md

param(
    [switch]$Installer,
    [switch]$SkipSign
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Error "Run scripts\setup_dev.cmd first."
}

function Get-AppVersion {
    $toml = Join-Path $Root "pyproject.toml"
    if (-not (Test-Path -LiteralPath $toml)) { return "0.1.0" }
    $line = Select-String -Path $toml -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value }
    return "0.1.0"
}

$AppVersion = Get-AppVersion

# Do not redirect native stderr with 2>$null — PowerShell turns it into a terminating error.
& $Py -m pip install -q pyinstaller Pillow
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Py scripts\prepare_branding_assets.py
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Branding icons missing — place logo PNG or fix assets path, then re-run."
}

& $Py -m pip install -q -e ".[gui,packaging]"
if ($LASTEXITCODE -ne 0) { Write-Warning "pip install -e .[gui,packaging] returned $LASTEXITCODE" }

$Icon = Join-Path $Root "app\resources\ncurity_app_icon.ico"
if (-not (Test-Path -LiteralPath $Icon)) {
    Write-Error "Missing $Icon — run: .venv\Scripts\python.exe scripts\prepare_branding_assets.py"
}

& $Py scripts\generate_version_info.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# OneDrive often locks build\localpycs; --clean then fails with WinError 5.
$WorkPath = Join-Path $Root "build\ncurity_f5tool"
if (Test-Path -LiteralPath $WorkPath) {
    cmd /c "rd /s /q `"$WorkPath`""
}

& $Py -m PyInstaller packaging\ncurity_f5tool.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$DistDir = Join-Path $Root "dist\NcurityF5Tool"
$Exe = Join-Path $DistDir "NcurityF5Tool.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    Write-Error "Build failed: $Exe not found"
}

if (-not $SkipSign) {
    & (Join-Path $PSScriptRoot "sign_windows_release.ps1") -TargetPath $DistDir -Recurse
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Portable ZIP (one-folder — preferred for EDR vs one-file)
$ReleaseDir = Join-Path $Root "dist\release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ZipName = "NcurityF5Tool-$AppVersion-win64-portable.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -LiteralPath $DistDir -DestinationPath $ZipPath -CompressionLevel Optimal

$hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
$manifestPath = Join-Path $ReleaseDir "NcurityF5Tool-$AppVersion-release-manifest.txt"
@(
    "Ncurity F5 Big-IP Managing Tool — release manifest"
    "Version: $AppVersion"
    "Built: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    ""
    "Portable ZIP: $ZipName"
    "SHA256: $hash"
    ""
    "Main executable: NcurityF5Tool.exe"
    "Process name: NcurityF5Tool.exe"
    "Publisher (when signed): Ncurity"
    "Install location (installer): %LOCALAPPDATA%\Programs\Ncurity\F5 Big-IP Managing Tool"
    "User data / reports: %LOCALAPPDATA%\f5tool\"
    ""
    "Network: HTTPS 443 to F5 MGMT; SSH port 22 not used."
) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host ""
Write-Host "Portable build: $Exe"
Write-Host "ZIP:          $ZipPath"
Write-Host "SHA256:       $hash"
Write-Host "Manifest:     $manifestPath"

if ($Installer) {
    $msiArgs = @()
    if ($SkipSign) { $msiArgs += "-SkipSign" }
    & (Join-Path $PSScriptRoot "build_msi.ps1") @msiArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Msi = Join-Path $Root "dist\installer\NcurityF5Tool-$AppVersion.msi"
    if (Test-Path -LiteralPath $Msi) {
        $msiHash = (Get-FileHash -LiteralPath $Msi -Algorithm SHA256).Hash
        Add-Content -LiteralPath $manifestPath -Encoding UTF8 -Value @(
            "",
            "Installer: dist\installer\NcurityF5Tool-$AppVersion.msi",
            "Installer SHA256: $msiHash",
            "Installed program: NcurityF5Tool.exe"
        )
    }
}

Write-Host ""
Write-Host "Delivery: give the MSI installer. The program itself is NcurityF5Tool.exe."
Write-Host "Details: docs\customer_delivery.md"
