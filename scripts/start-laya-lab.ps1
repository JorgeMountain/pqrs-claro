$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $taskRoot) -ne 'pqrs-claro-fiaga') {
    throw 'Este acceso solo corresponde a la copia aislada FIAGA.'
}
$listener = Get-NetTCPConnection -State Listen -LocalPort 8775 -ErrorAction SilentlyContinue
if ($listener) {
    $running = $null
    try { $running = Invoke-RestMethod 'http://127.0.0.1:8775/laya-lab-environment' -TimeoutSec 2 } catch {}
    if ($running -and $running.code_root -eq $taskRoot -and $running.environment -eq 'fiaga-laya-lab') {
        Write-Output 'Banco FIAGA + Laya disponible: http://127.0.0.1:8775/'
        return
    }
    throw 'El puerto 8775 está ocupado por otra aplicación. No se detuvo ningún proceso.'
}
Write-Output 'Banco temporal FIAGA + Laya: http://127.0.0.1:8775/'
& "$PSScriptRoot\dev-python.ps1" "$PSScriptRoot\run-laya-lab.py"
exit $LASTEXITCODE
