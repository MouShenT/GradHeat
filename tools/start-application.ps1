param(
    [string]$PythonPath = 'D:\software\python3.12\python.exe',
    [ValidateRange(1024,65535)][int]$JavaPort = 18729,
    [ValidateRange(1024,65535)][int]$PythonPort = 18730,
    [switch]$NoWorker
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Specify the local Python 3.12 executable with -PythonPath.' }
$launcherArgs = @('-X','utf8','-B',(Join-Path $projectRoot 'tools\application\launcher.py'),'--java-port',"$JavaPort",'--python-port',"$PythonPort")
if ($NoWorker) { $launcherArgs += '--no-worker' }
& $PythonPath @launcherArgs
exit $LASTEXITCODE
