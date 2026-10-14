param([string]$Binary = '', [string]$ReportName = 'frozen-smoke')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ($ReportName -notmatch '^[a-z0-9-]+$') { throw 'Invalid report name.' }
if (-not $Binary) { $Binary = Join-Path $projectRoot 'dist\FilePilot\FilePilot.exe' }
$Binary = (Resolve-Path -LiteralPath $Binary).Path
$report = Join-Path $projectRoot "artifacts\$ReportName.json"
$dataDirectory = Join-Path $projectRoot "artifacts\qa-state\$ReportName"
$priorEnvironment = @{}
$variableNames = @('PATH', 'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QT_QPA_PLATFORM')
foreach ($name in $variableNames) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PATH = "$env:WINDIR\System32;$env:WINDIR"
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $env:QT_PLUGIN_PATH = $null
    $env:QML2_IMPORT_PATH = $null
    $env:QT_QPA_PLATFORM = 'windows'
    $testStart = [DateTime]::UtcNow
    $arguments = @('--data-dir', ('"{0}"' -f $dataDirectory), '--smoke-test', ('"{0}"' -f $report))
    $process = Start-Process -FilePath $Binary -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(20000)) {
        Stop-Process -Id $process.Id
        throw 'Executable startup timed out.'
    }
    if ($process.ExitCode -ne 0) { throw "Executable exited with $($process.ExitCode)." }
    if (-not (Test-Path -LiteralPath $report)) { throw 'Executable did not write its startup report.' }
    if ((Get-Item -LiteralPath $report).LastWriteTimeUtc -lt $testStart) { throw 'Startup report is stale.' }
    $payload = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if (-not $payload.ok -or -not $payload.frozen -or -not $payload.database_created -or $payload.pages -ne 3 -or -not $payload.window_icon -or $payload.app_user_model_id -ne 'FilePilot.Desktop') {
        throw 'Executable startup checks did not pass.'
    }
    $payload | Add-Member -NotePropertyName native_windows -NotePropertyValue $true
    $payload | Add-Member -NotePropertyName isolated_search_path -NotePropertyValue $true
    $payload | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding utf8
    $payload | ConvertTo-Json
} finally {
    foreach ($name in $variableNames) {
        [Environment]::SetEnvironmentVariable($name, $priorEnvironment[$name], 'Process')
    }
}
