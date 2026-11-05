# gui launcher — safe for paths containing "&"
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $root
Write-Host "[f5tool] project: $root"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    throw "run scripts\setup_dev.cmd first"
}
& $py -m app.gui.main
exit $LASTEXITCODE
