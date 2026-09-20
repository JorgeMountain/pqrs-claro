param([ValidateRange(1, 65535)][int]$Port = 8772)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\start-unificado.ps1" -Port $Port
exit $LASTEXITCODE
