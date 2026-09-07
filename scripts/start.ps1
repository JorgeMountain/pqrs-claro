$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\dev-python.ps1" -m pqrs_claro.app @args
exit $LASTEXITCODE
