param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            Write-Host "creating .venv with: py -3"
            & py -3 -m venv .venv
            if ($LASTEXITCODE -ne 0) {
                Write-Host "retry: py -3.14 -m venv .venv"
                & py -3.14 -m venv .venv
            }
        }
        elseif (Get-Command python -ErrorAction SilentlyContinue) {
            $probe = & python -c "import sys; print(sys.executable)" 2>&1
            if ($LASTEXITCODE -eq 0 -and "$probe" -notmatch "WindowsApps") {
                & python -m venv .venv
            }
            else {
                throw "python is the microsoft store stub. see docs/windows_setup.md"
            }
        }
        else {
            throw "no py/python found. install python 3.12+ first."
        }
    }
    finally {
        $ErrorActionPreference = $prev
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "failed to create .venv under $ProjectRoot"
    }
}

Write-Host "python: $venvPython"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venvPython -m pip install -r requirements_dev.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "setup complete. next:"
Write-Host "  scripts\run_tests.cmd"
