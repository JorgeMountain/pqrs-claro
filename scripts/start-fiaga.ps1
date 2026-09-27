$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $taskRoot) -ne 'pqrs-claro-fiaga') {
    throw 'Este acceso solo corresponde a la copia de desarrollo FIAGA.'
}
$taskRunning = $null
try { $taskRunning = Invoke-RestMethod 'http://127.0.0.1:8773/fiaga-environment' -TimeoutSec 2 } catch {}
if ($taskRunning) {
    if ($taskRunning.code_root -ne $taskRoot -or $taskRunning.environment -ne 'desarrollo-fiaga') {
        throw 'El puerto 8773 corresponde a otro entorno.'
    }
    Write-Output 'Desarrollo FIAGA disponible: http://127.0.0.1:8773/'
    return
}
Write-Output 'DESARROLLO FIAGA - datos independientes - http://127.0.0.1:8773/'
& "$PSScriptRoot\dev-python.ps1" "$PSScriptRoot\run-fiaga.py"
exit $LASTEXITCODE
