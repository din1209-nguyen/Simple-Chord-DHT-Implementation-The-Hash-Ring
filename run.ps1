$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

function Get-ProjectPython {
    $candidates = @(
        @{ Command = "py"; Args = @("-3.10") },
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }

        try {
            $versionText = & $candidate.Command @($candidate.Args + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"))
            $parts = $versionText.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -eq 3 -and $minor -ge 10) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python 3.10+ was not found. Install Python from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'."
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Test-ProjectVenv {
    if (-not (Test-Path $venvPython)) {
        return $false
    }

    try {
        & $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & $venvPython -m pip --version | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Reset-ProjectVenv {
    $venvPath = Join-Path $PSScriptRoot ".venv"
    if (-not (Test-Path $venvPath)) {
        return
    }

    $rootPath = [System.IO.Path]::GetFullPath($PSScriptRoot)
    $resolvedVenv = [System.IO.Path]::GetFullPath((Resolve-Path $venvPath).Path)
    if (-not $resolvedVenv.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected virtual environment path: $resolvedVenv"
    }

    Write-Host "Removing unusable .venv ..."
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

if (-not (Test-ProjectVenv)) {
    Reset-ProjectVenv
    $python = Get-ProjectPython
    Write-Host "Creating virtual environment in .venv ..."
    & $python.Command @($python.Args + @("-m", "venv", ".venv"))
}

Write-Host "Installing project dependencies ..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[dev]"

if (-not $env:HOST) {
    $env:HOST = "127.0.0.1"
}

if (-not $env:PORT) {
    $env:PORT = "5000"
}

Write-Host "Starting Simple Chord DHT at http://$($env:HOST):$($env:PORT)"
& $venvPython app.py
