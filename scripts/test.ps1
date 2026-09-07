$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try { & "$PSScriptRoot\dev-python.ps1" -m pytest -q @args } finally { Pop-Location }
exit $LASTEXITCODE
