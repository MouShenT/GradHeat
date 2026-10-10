param(
    [ValidateSet('Start','Stop','Restart','Status')][string]$Mode = 'Start',
    [string]$PythonPath = '',
    [string]$NodePath = '',
    [string]$JavaPath = '',
    [string]$JarPath = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeFolder = Join-Path $projectRoot '.research\frontend-dev'
$configPath = Join-Path $runtimeFolder 'config.json'
$stopPath = Join-Path $runtimeFolder 'stop'
$runtimePath = Join-Path $runtimeFolder 'runtime.json'
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $taskHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-','').Substring(0,8).ToLowerInvariant() }
finally { $hasher.Dispose() }
$taskName = "GradHeat-Frontend-$taskHash"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($Mode -eq 'Status') {
    [pscustomobject]@{ Task = $taskName; SchedulerState = if ($task) { "$($task.State)" } else { 'NotInstalled' }; URL = 'http://127.0.0.1:5173/' } | ConvertTo-Json
    if (Test-Path -LiteralPath $runtimePath) { Get-Content -LiteralPath $runtimePath }
    exit 0
}
if ($Mode -in 'Stop','Restart') {
    if ($task) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    if (Test-Path -LiteralPath $runtimeFolder) { Set-Content -LiteralPath $stopPath -Value 'stop' -Encoding utf8 }
    $deadline = (Get-Date).AddSeconds(35)
    while ($task -and (Get-Date) -lt $deadline) {
        $task = Get-ScheduledTask -TaskName $taskName
        if ($task.State -ne 'Running') { break }
        Start-Sleep -Milliseconds 500
    }
    if ($task -and $task.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    if ($Mode -eq 'Stop') { Write-Output 'Frontend and its API stopped; automatic login startup disabled.'; exit 0 }
}
if ($Mode -eq 'Start' -and $task -and $task.State -eq 'Running') {
    Start-Process 'http://127.0.0.1:5173/'
    Write-Output 'Frontend already runs independently at http://127.0.0.1:5173/'; exit 0
}
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe).Source }
if (-not $NodePath) { $NodePath = (Get-Command node.exe).Source }
if (-not $JavaPath) { $JavaPath = (Get-Command java.exe).Source }
if (-not $JarPath) {
    $JarPath = Join-Path $projectRoot 'backend\target\gradheat-backend-0.1.0.jar'
    $buildPointer = Join-Path $runtimeFolder 'backend-build.json'
    if (Test-Path -LiteralPath $buildPointer) { $JarPath = (Get-Content -LiteralPath $buildPointer -Raw | ConvertFrom-Json).jar }
}
$PythonWindowless = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
foreach ($requiredPath in @($PythonPath,$PythonWindowless,$NodePath,$JavaPath,$JarPath,(Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required runtime/build is missing: $requiredPath" }
}
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null
Remove-Item -LiteralPath $stopPath -ErrorAction SilentlyContinue
$config = @{
    runtime_dir = $runtimeFolder; task_name = $taskName; python = $PythonPath
    node = $NodePath; java = $JavaPath; jar = $JarPath; open_browser = $true
    repository_sync = $true; sync_interval_seconds = 900
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
$supervisorPath = Join-Path $projectRoot 'tools\application\dev_supervisor.py'
$actionArgs = '-X utf8 -B "{0}" --config "{1}"' -f $supervisorPath,$configPath
$action = New-ScheduledTaskAction -Execute $PythonWindowless -Argument $actionArgs -WorkingDirectory $projectRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Description "Independent GradHeat Vite hot reload + API for $projectRoot; no collector workers." -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output 'Windows owns this service; closing Codex will not stop it. URL: http://127.0.0.1:5173/'
