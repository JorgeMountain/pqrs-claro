param([ValidateRange(1, 65535)][int]$Port = 8772)
$ErrorActionPreference = 'Stop'
$taskListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($taskListener) {
    $taskStatus = Invoke-RestMethod "http://127.0.0.1:$Port/recorrido-status" -TimeoutSec 10
    if ($taskStatus.interface -ne 'recorrido' -or $taskStatus.mode -ne 'unified') {
        throw "El puerto $Port está ocupado por otra aplicación o por el recorrido de dos puertos. No se detuvo ningún proceso."
    }
    Invoke-RestMethod "http://127.0.0.1:$Port/api/config" -TimeoutSec 10 | Out-Null
    Write-Output "Sistema unificado disponible: http://127.0.0.1:$Port/"
    return
}
$taskPrevious = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python' -and $_.CommandLine -match '-m pqrs_claro\.app(?:\s|$)'
}
if ($taskPrevious) {
    throw 'El servicio anterior sigue activo. Detén ese servicio antes de abrir el modo unificado con los mismos datos. No se detuvo ningún proceso.'
}
Write-Output "Sistema unificado: http://127.0.0.1:$Port/"
& "$PSScriptRoot\dev-python.ps1" -m pqrs_claro.unified_app --port $Port
exit $LASTEXITCODE
