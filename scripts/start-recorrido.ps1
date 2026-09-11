$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPrototype = Join-Path $taskRoot 'src\pqrs_claro\static\recorrido'
if (-not (Test-Path -LiteralPath (Join-Path $taskPrototype 'index.html'))) {
    throw 'No se encuentra la interfaz del recorrido.'
}
$taskListener = Get-NetTCPConnection -State Listen -LocalPort 8772 -ErrorAction SilentlyContinue
if ($taskListener) {
    $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8772/recorrido-status' -TimeoutSec 10
    if ($taskStatus.interface -ne 'recorrido') { throw 'El puerto 8772 está ocupado por otra página.' }
    Invoke-RestMethod 'http://127.0.0.1:8772/api/config' -TimeoutSec 10 | Out-Null
    Write-Output 'Recorrido de trabajo disponible: http://127.0.0.1:8772/'
    return
}
$taskBackend = Get-NetTCPConnection -State Listen -LocalPort 8770 -ErrorAction SilentlyContinue
if (-not $taskBackend) {
    $taskPython = (uv python find --system 3.12).Trim()
    $taskLogs = Join-Path $taskRoot 'output\runtime'
    New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
    $env:PYTHONPATH = "$(Join-Path $taskRoot '.runtime\Lib\site-packages');$(Join-Path $taskRoot 'src')"
    $env:PQRS_CLARO_DATA_DIR = Join-Path $taskRoot 'data'
    $env:PQRS_CLARO_PORT = '8770'
    Start-Process -FilePath $taskPython -ArgumentList '-m','pqrs_claro.app' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogs 'backend-out.log') -RedirectStandardError (Join-Path $taskLogs 'backend-error.log') | Out-Null
}
Write-Output 'Recorrido de trabajo con biblioteca real: http://127.0.0.1:8772/'
& "$PSScriptRoot\dev-python.ps1" -m pqrs_claro.recorrido_app --port 8772 --backend-port 8770
exit $LASTEXITCODE
