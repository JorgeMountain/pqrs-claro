$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BasePython = (uv python find --system 3.12 2>$null)
if (-not $BasePython) { $BasePython = (uv python find --no-project --managed-python 3.12) }
$BasePython = "$BasePython".Trim()
if (-not $BasePython) { throw 'No se encontró Python 3.12. Ejecute: uv python install 3.12' }
$SitePackages = Join-Path $ProjectRoot '.runtime\Lib\site-packages'
New-Item -ItemType Directory -Path $SitePackages -Force | Out-Null
Push-Location $ProjectRoot
try {
    uv export --frozen --all-groups --no-hashes --no-emit-project --output-file '.runtime\requirements.txt' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No fue posible exportar dependencias.' }
    uv pip install --python $BasePython --target $SitePackages --requirements '.runtime\requirements.txt'
    if ($LASTEXITCODE -ne 0) { throw 'No fue posible instalar dependencias.' }
} finally { Pop-Location }
# PYTHONPATH entries do not process .pth files. Load the project's site-packages
# as a site directory so pywin32's bootstrap and DLL paths are initialized.
$BootstrapPath = Join-Path $SitePackages 'sitecustomize.py'
@'
from pathlib import Path
import site
site.addsitedir(str(Path(__file__).resolve().parent))
'@ | Set-Content -LiteralPath $BootstrapPath -Encoding ascii
Write-Host 'Dependencias listas. Inicie con .\scripts\start.ps1'
