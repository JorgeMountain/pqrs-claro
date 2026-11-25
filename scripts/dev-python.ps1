param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BasePython = (uv python find --system 3.12 2>$null)
if (-not $BasePython) { $BasePython = (uv python find --no-project --managed-python 3.12) }
$BasePython = "$BasePython".Trim()
if (-not $BasePython) { throw 'No se encontró Python 3.12. Ejecute: uv python install 3.12' }
$SitePackages = Join-Path $ProjectRoot '.runtime\Lib\site-packages'
if (-not (Test-Path -LiteralPath $SitePackages)) { throw 'Ejecute primero scripts\setup.ps1' }
$env:PYTHONPATH = "$SitePackages;$(Join-Path $ProjectRoot 'src')"
& $BasePython @PythonArgs
exit $LASTEXITCODE
