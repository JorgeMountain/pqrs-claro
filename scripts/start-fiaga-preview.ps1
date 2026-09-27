$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $taskRoot) -ne 'pqrs-claro-fiaga') {
    throw 'Este acceso solo corresponde a FIAGA.'
}
$taskPreview = $null
try { $taskPreview = Invoke-RestMethod 'http://127.0.0.1:8774/fiaga-environment' -TimeoutSec 2 } catch {}
if ($taskPreview) {
    if ($taskPreview.code_root -ne $taskRoot -or $taskPreview.environment -ne 'desarrollo-fiaga-fase2') {
        throw 'El puerto 8774 corresponde a otro entorno.'
    }
    Write-Output 'Vista FIAGA fase 2: http://127.0.0.1:8774/'
    return
}
& "$PSScriptRoot\dev-python.ps1" "$PSScriptRoot\run-fiaga-preview.py"
exit $LASTEXITCODE
