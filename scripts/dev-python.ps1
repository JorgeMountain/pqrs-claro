param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BasePython = (uv python find --system 3.12).Trim()
$SitePackages = Join-Path $ProjectRoot '.runtime\Lib\site-packages'
if (-not (Test-Path -LiteralPath $SitePackages)) { throw 'Ejecute primero scripts\setup.ps1' }
$env:PYTHONPATH = "$SitePackages;$(Join-Path $ProjectRoot 'src')"
& $BasePython @PythonArgs
exit $LASTEXITCODE
