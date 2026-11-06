# Build a per-user MSI from dist\NcurityF5Tool.
# The installed program is still NcurityF5Tool.exe.
# Requires WiX Toolset 5.

param(
    [switch]$SkipSign
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Get-AppVersion {
    $toml = Join-Path $Root "pyproject.toml"
    $line = Select-String -Path $toml -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value }
    return "1.2.0"
}

function Find-Wix {
    $candidates = @(
        "$env:ProgramFiles\WiX Toolset v5.0\bin\wix.exe",
        "${env:ProgramFiles(x86)}\WiX Toolset v5.0\bin\wix.exe",
        (Join-Path $env:TEMP "wix5\PFiles64\WiX Toolset v5.0\bin\wix.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $cmd = Get-Command wix.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "WiX 5 not found. Install WiX Toolset v5."
}

$DistDir = Join-Path $Root "dist\NcurityF5Tool"
$Exe = Join-Path $DistDir "NcurityF5Tool.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Missing $Exe — run scripts\build_windows.ps1 first."
}

$AppVersion = Get-AppVersion
$parts = @($AppVersion.Split(".") + @("0", "0", "0", "0"))[0..3]
$ProductVersion = ($parts -join ".")
$Wix = Find-Wix
$Stage = Join-Path $env:TEMP "ncurity-f5tool-msi-src"
$OutDir = Join-Path $env:TEMP "ncurity-f5tool-msi-out"
foreach ($dir in @($Stage, $OutDir)) {
    if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Host "Staging app files..."
& robocopy $DistDir $Stage /E /NFL /NDL /NJH /NJS /nc /ns | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit $LASTEXITCODE" }

$Icon = Join-Path $Root "app\resources\ncurity_app_icon.ico"
$Product = Join-Path $Root "packaging\msi\Product.wxs"
$MsiName = "NcurityF5Tool-$AppVersion.msi"
$Msi = Join-Path $OutDir $MsiName
Write-Host "Building MSI..."
& $Wix build -arch x64 -dcl high `
    -d "SourceDir=$Stage" `
    -d "ProductVersion=$ProductVersion" `
    -d "AppIcon=$Icon" `
    -o $Msi `
    $Product
if ($LASTEXITCODE -ne 0) { throw "wix build failed: $LASTEXITCODE" }

if (-not $SkipSign) {
    & (Join-Path $PSScriptRoot "sign_windows_release.ps1") -TargetPath $Msi
    if ($LASTEXITCODE -ne 0) { throw "MSI signing failed" }
}

$DistInstaller = Join-Path $Root "dist\installer"
New-Item -ItemType Directory -Force -Path $DistInstaller | Out-Null
$Copied = Join-Path $DistInstaller $MsiName
Copy-Item -LiteralPath $Msi -Destination $Copied -Force
$hash = (Get-FileHash -LiteralPath $Msi -Algorithm SHA256).Hash
Write-Host ""
Write-Host "MSI:    $Msi"
Write-Host "Copied: $Copied"
Write-Host "SHA256: $hash"
