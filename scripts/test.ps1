$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if ($args.Count -gt 0) {
        & "$PSScriptRoot\dev-python.ps1" -m pytest -q @args
        exit $LASTEXITCODE
    }
    & "$PSScriptRoot\dev-python.ps1" -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$PSScriptRoot\dev-python.ps1" -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    node --test tests/*.mjs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$PSScriptRoot\dev-python.ps1" -PythonArgs @(
        '-m', 'pytest', '-q', '-ra', '-o', 'python_files=check_*_browser.py', 'tests'
    )
    exit $LASTEXITCODE
} finally { Pop-Location }
