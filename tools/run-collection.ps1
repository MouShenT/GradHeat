param(
    [ValidateSet('prepare','check','run','status','export')][string]$Action = 'run',
    [string]$PythonPath = 'D:\software\python3.12\python.exe',
    [string]$Batch,
    [string]$InputJson,
    [int]$MaxJobs = 0,
    [double]$Hours = 8,
    [ValidateSet('official','social','github')][string[]]$Channel,
    [ValidateSet('xhs','zhihu','dy','bili')][string[]]$RetryPlatform,
    [switch]$OnlyIngest,
    [int]$UnitLimit = 0
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$previousPythonPath=$env:PYTHONPATH
$env:PYTHONPATH=Join-Path $projectRoot 'python_service'
try {
    $collectorArgs=@('-X','utf8','-B','-m','gradheat_python.collection_cli',$Action)
    if($Action -eq 'prepare') {
        $collectorArgs+='--from-existing'
        if($UnitLimit -gt 0) {$collectorArgs+=@('--unit-limit',"$UnitLimit")}
    } else {
        if($Action -eq 'run' -and -not ($InputJson -or $Batch)) {throw 'Specify -InputJson for a new run or -Batch to resume.'}
        if($InputJson) {$collectorArgs+=@('--input',$InputJson)}
        if($Batch) {$collectorArgs+=@('--batch',$Batch)}
        if($Action -eq 'run') {
            $collectorArgs+=@('--max-jobs',"$MaxJobs")
            if($PSBoundParameters.ContainsKey('Hours')) {$collectorArgs+=@('--hours',"$Hours")}
            foreach($item in $Channel) {$collectorArgs+=@('--channel',$item)}
            foreach($item in $RetryPlatform) {$collectorArgs+=@('--retry-platform',$item)}
            if($OnlyIngest) {$collectorArgs+='--only-ingest'}
        }
    }
    & $PythonPath @collectorArgs
    $collectorExitCode=$LASTEXITCODE
} finally {$env:PYTHONPATH=$previousPythonPath}
exit $collectorExitCode
