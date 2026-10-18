param(
    [ValidateSet('Start','Stop','Restart','Status')][string]$Mode = 'Start',
    [string]$PythonPath = '',
    [string[]]$QueueFolder = @()
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeFolder = Join-Path $projectRoot '.research\collection-service'
$configPath = Join-Path $runtimeFolder 'config.json'
$stopPath = Join-Path $runtimeFolder 'stop'
$restartPath = Join-Path $runtimeFolder 'restart'
$runtimePath = Join-Path $runtimeFolder 'runtime.json'
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $taskHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-','').Substring(0,8).ToLowerInvariant() }
finally { $hasher.Dispose() }
$taskName = "GradHeat-Collector-$taskHash"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($Mode -eq 'Status') {
    [pscustomobject]@{ Task = $taskName; SchedulerState = if ($task) { "$($task.State)" } else { 'NotInstalled' } } | ConvertTo-Json
    if (Test-Path -LiteralPath $runtimePath) { Get-Content -LiteralPath $runtimePath }
    exit 0
}
if ($Mode -in 'Stop','Restart' -and $task -and $task.State -eq 'Running') {
    if ($Mode -eq 'Stop') { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    else { Set-Content -LiteralPath $restartPath -Value 'restart after current batch' -Encoding utf8 }
    Set-Content -LiteralPath $stopPath -Value 'finish current batch' -Encoding utf8
    Write-Output 'Requested completion of the current batch. No collection process was terminated.'
    exit 0
}
if ($Mode -eq 'Stop') {
    if ($task) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    if (Test-Path -LiteralPath $runtimeFolder) { Set-Content -LiteralPath $stopPath -Value 'stop' -Encoding utf8 }
    Write-Output 'Collection startup disabled. Existing checkpoints remain intact.'
    exit 0
}
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe).Source }
$pythonWindowless = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
foreach ($requiredPath in @($PythonPath,$pythonWindowless)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required Python runtime is missing: $requiredPath" }
}
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null
$config = @{}
if (Test-Path -LiteralPath $configPath) {
    $existing = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    foreach ($property in $existing.PSObject.Properties) { $config[$property.Name] = $property.Value }
}
if ($QueueFolder.Count) {
    $privateRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.research')) + [IO.Path]::DirectorySeparatorChar
    $queues = @()
    foreach ($queue in $QueueFolder) {
        $absolute = if ([IO.Path]::IsPathRooted($queue)) { [IO.Path]::GetFullPath($queue) } else { [IO.Path]::GetFullPath((Join-Path $projectRoot $queue)) }
        if (-not $absolute.StartsWith($privateRoot,[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath (Join-Path $absolute 'queue.json') -PathType Leaf)) { throw 'Each queue must be an existing frozen folder inside .research.' }
        $queues += $absolute
    }
    $config.queues = $queues
}
if (-not $config.queues) { throw 'Configure ordered frozen queues in .research/collection-service/config.json or pass -QueueFolder.' }
$config.runtime_dir = $runtimeFolder
$config.task_name = $taskName
$config.python = $PythonPath
if (-not $config.ContainsKey('budget_hours')) { $config.budget_hours = 8 }
if (-not $config.ContainsKey('interval_seconds')) { $config.interval_seconds = 15 }
$temporaryConfig = Join-Path $runtimeFolder ('config-' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    $config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryConfig -Encoding utf8
    & $PythonPath -X utf8 -B -c 'import sys; from pathlib import Path; sys.path.insert(0,str(Path(sys.argv[1])/"tools/application")); from collection_supervisor import load_config; load_config(Path(sys.argv[2]))' $projectRoot $temporaryConfig
    if ($LASTEXITCODE -ne 0) { throw 'Collection configuration validation failed; existing config was retained.' }
    Move-Item -LiteralPath $temporaryConfig -Destination $configPath -Force
}
finally { if (Test-Path -LiteralPath $temporaryConfig) { Remove-Item -LiteralPath $temporaryConfig } }
Remove-Item -LiteralPath $stopPath,$restartPath -ErrorAction SilentlyContinue
if ($Mode -eq 'Start' -and $task -and $task.State -eq 'Running') {
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Output 'Collector already runs independently; its configuration was validated.'
    exit 0
}
$supervisorPath = Join-Path $projectRoot 'tools\application\collection_supervisor.py'
$actionArgs = '-X utf8 -B "{0}" --config "{1}"' -f $supervisorPath,$configPath
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $actionArgs -WorkingDirectory $projectRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Description "Independent GradHeat frozen collection queues for $projectRoot; preserves uncertain checkpoints and never starts a browser." -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output 'Windows owns collection supervision. Closing this chat will not stop it; unavailable browsers and uncertain checkpoints remain paused.'
