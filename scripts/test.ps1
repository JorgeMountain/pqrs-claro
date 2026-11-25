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
    exit $LASTEXITCODE
} finally { Pop-Location }
