param([switch]$Demo, [string]$DataDir = "")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction Stop).Source }
$launchArgs = @((Join-Path $PSScriptRoot 'run.py'))
if ($Demo) { $launchArgs += '--demo' }
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
& $pythonExe @launchArgs
exit $LASTEXITCODE
