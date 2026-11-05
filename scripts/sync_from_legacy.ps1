# one-time copy from old dev folder (C:\Users\ejes3) into this project root
param(
    [string]$SourceRoot = "C:\Users\ejes3"
)

$ErrorActionPreference = "Stop"
$DestRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "source: $SourceRoot"
Write-Host "dest:   $DestRoot"

if (-not (Test-Path -LiteralPath $SourceRoot)) {
    throw "source not found: $SourceRoot"
}

$dirs = @("app", "docs", "tests", "tools", "templates", "scripts")
$files = @("pyproject.toml", "requirements.txt", "requirements_dev.txt", "readme.md", ".gitignore")

foreach ($d in $dirs) {
    $from = Join-Path $SourceRoot $d
    if (Test-Path -LiteralPath $from) {
        $to = Join-Path $DestRoot $d
        Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
        Write-Host "copied dir: $d"
    }
}

foreach ($f in $files) {
    $from = Join-Path $SourceRoot $f
    if (Test-Path -LiteralPath $from) {
        Copy-Item -LiteralPath $from -Destination (Join-Path $DestRoot $f) -Force
        Write-Host "copied file: $f"
    }
}

$exclude = @(".venv", "output", "__pycache__", ".pytest_cache", ".cursor")
foreach ($ex in $exclude) {
    Get-ChildItem -LiteralPath $DestRoot -Recurse -Directory -Filter $ex -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not (Test-Path -LiteralPath (Join-Path $DestRoot ".git"))) {
    Push-Location -LiteralPath $DestRoot
    git init | Write-Host
    Pop-Location
}

Write-Host "done. open this folder in cursor as workspace root."
