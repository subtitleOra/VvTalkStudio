$ErrorActionPreference = 'Stop'
$taskStatus = Join-Path $env:USERPROFILE 'AppData\Local\VvTalkStudio\runtime.json'
if (-not (Test-Path -LiteralPath $taskStatus)) { exit 0 }
$taskState = Get-Content -LiteralPath $taskStatus -Raw | ConvertFrom-Json
$taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskState.pid)" -ErrorAction SilentlyContinue
if ($taskProcess -and ($taskProcess.Name -eq 'VvTalkStudio.exe' -or $taskProcess.CommandLine -like '*VvTalkStudio*app.py*')) {
    Stop-Process -Id $taskProcess.ProcessId
}
