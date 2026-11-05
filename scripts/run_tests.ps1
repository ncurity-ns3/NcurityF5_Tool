$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonExe = (Resolve-Path -LiteralPath $venvPython).Path
    Write-Host "using project venv: $pythonExe"
}
else {
    . (Join-Path $PSScriptRoot "find_python.ps1")
    $pythonExe = Get-ProjectPython -ProjectRoot $root
    Write-Host "using: $pythonExe"
}

& $pythonExe --version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $pythonExe tools/check_naming.py .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $pythonExe -m pytest tests -v
exit $LASTEXITCODE
