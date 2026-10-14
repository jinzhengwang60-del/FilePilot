param([string]$Python = "")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
$buildOutput = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'dist\FilePilot'))
$projectPrefix = $projectRoot + [System.IO.Path]::DirectorySeparatorChar
if (-not $buildOutput.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must remain inside this project.'
}
foreach ($entryPath in @($projectRoot, (Join-Path $projectRoot 'dist'), $buildOutput)) {
    if (Test-Path -LiteralPath $entryPath) {
        $entry = Get-Item -LiteralPath $entryPath -Force
        if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw 'Build output must not use junctions or symbolic links.'
        }
    }
}
if (-not $Python) {
    $localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction Stop).Source }
}
$priorPythonPath = $env:PYTHONPATH
try {
    $buildTools = Join-Path $projectRoot '.build-tools'
    if (Test-Path -LiteralPath (Join-Path $buildTools 'PyInstaller')) {
        $env:PYTHONPATH = if ($priorPythonPath) { "$buildTools;$priorPythonPath" } else { $buildTools }
    }
    & $Python -m PyInstaller --noconfirm 'FilePilot.spec'
    if ($LASTEXITCODE -ne 0) { throw 'Build failed. Install requirements-dev.txt first.' }
} finally {
    $env:PYTHONPATH = $priorPythonPath
}
Write-Output (Join-Path $projectRoot 'dist\FilePilot\FilePilot.exe')
