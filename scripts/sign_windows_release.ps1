# Authenticode-sign PyInstaller output (optional; strongly recommended for EDR).
#
# Set ONE of:
#   NCURITY_SIGN_PFX_PATH  — path to .pfx
#   NCURITY_SIGN_PFX_BASE64 — base64 .pfx (CI)
#   NCURITY_SIGN_CERT_SHA1 — thumbprint in Windows cert store (SignTool /sha1)
#
# Optional:
#   NCURITY_SIGN_PFX_PASSWORD
#   NCURITY_SIGN_TIMESTAMP_URL (default: http://timestamp.digicert.com)

param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,
    [switch]$Recurse
)

$ErrorActionPreference = "Stop"

function Get-SignToolPath {
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not (Test-Path -LiteralPath $kits)) {
        throw "Windows SDK SignTool not found. Install 'Windows SDK Signing Tools' or Visual Studio Build Tools."
    }
    $latest = Get-ChildItem -LiteralPath $kits -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $exe = Join-Path $latest.FullName "x64\signtool.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        $exe = Join-Path $latest.FullName "signtool.exe"
    }
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "signtool.exe not found under $kits"
    }
    return $exe
}

$thumb = $env:NCURITY_SIGN_CERT_SHA1
$pfxPath = $env:NCURITY_SIGN_PFX_PATH
$pfxB64 = $env:NCURITY_SIGN_PFX_BASE64
$tsUrl = if ($env:NCURITY_SIGN_TIMESTAMP_URL) { $env:NCURITY_SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }

if (-not $thumb -and -not $pfxPath -and -not $pfxB64) {
    Write-Host "Sign skipped (set NCURITY_SIGN_PFX_PATH or NCURITY_SIGN_CERT_SHA1)."
    exit 0
}

$signTool = Get-SignToolPath
$tempPfx = $null
if ($pfxB64 -and -not $pfxPath) {
    $tempPfx = Join-Path $env:TEMP ("ncurity-sign-{0}.pfx" -f [guid]::NewGuid().ToString("N"))
    [IO.File]::WriteAllBytes($tempPfx, [Convert]::FromBase64String($pfxB64))
    $pfxPath = $tempPfx
}

$files = @()
if (Test-Path -LiteralPath $TargetPath -PathType Container) {
    if ($Recurse) {
        $files = Get-ChildItem -LiteralPath $TargetPath -Recurse -File |
            Where-Object { $_.Extension -match '^\.(exe|dll)$' }
    }
    else {
        $files = Get-ChildItem -LiteralPath $TargetPath -File |
            Where-Object { $_.Extension -match '^\.(exe|dll)$' }
    }
}
elseif (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
    $files = @(Get-Item -LiteralPath $TargetPath)
}
else {
    throw "Not found: $TargetPath"
}

foreach ($file in $files) {
    $args = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $tsUrl, "/v")
    if ($thumb) {
        $args += @("/sha1", $thumb)
    }
    else {
        $args += @("/f", $pfxPath)
        if ($env:NCURITY_SIGN_PFX_PASSWORD) {
            $args += @("/p", $env:NCURITY_SIGN_PFX_PASSWORD)
        }
    }
    $args += $file.FullName
    Write-Host "Signing $($file.Name) ..."
    & $signTool @args
    if ($LASTEXITCODE -ne 0) {
        if ($tempPfx) { Remove-Item -LiteralPath $tempPfx -Force -ErrorAction SilentlyContinue }
        throw "SignTool failed for $($file.FullName)"
    }
}

if ($tempPfx) {
    Remove-Item -LiteralPath $tempPfx -Force -ErrorAction SilentlyContinue
}
Write-Host "Signed $($files.Count) file(s)."
