function Test-RealPython {
    param([string]$Exe)
    if (-not (Test-Path -LiteralPath $Exe)) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $out = & $Exe -c "import sys; print(sys.executable)" 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        $line = ($out | Where-Object { $_ -is [string] } | Select-Object -Last 1)
        if (-not $line) { return $false }
        return -not ("$line" -match "WindowsApps")
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

function Get-ProjectPython {
    param([string]$ProjectRoot = (Get-Location).Path)

    $candidates = @()

    if ($env:VIRTUAL_ENV) {
        $candidates += (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")
    }

    $candidates += (Join-Path $ProjectRoot ".venv\Scripts\python.exe")

    foreach ($exe in $candidates | Select-Object -Unique) {
        if (Test-RealPython -Exe $exe) {
            return (Resolve-Path -LiteralPath $exe).Path
        }
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            foreach ($ver in @("-3", "-3.14", "-3.13", "-3.12", "-3.11")) {
                $out = & py $ver -c "import sys; print(sys.executable)" 2>&1
                $line = ($out | Where-Object { $_ -is [string] -and $_ -match "\\" } | Select-Object -Last 1)
                if ($line) { $candidates += "$line".Trim() }
            }
        }
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $candidates += (Get-Command python).Source
        }
    }
    finally {
        $ErrorActionPreference = $prev
    }

    foreach ($exe in $candidates | Select-Object -Unique) {
        if (Test-RealPython -Exe $exe) {
            return (Resolve-Path -LiteralPath $exe).Path
        }
    }

    throw @"
python not found.

1) run: scripts\setup_dev.cmd
2) or install python 3.12+ and disable store python aliases
see docs/windows_setup.md
"@
}
