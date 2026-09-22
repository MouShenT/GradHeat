param([string]$Query, [switch]$Health)
$ErrorActionPreference = 'Stop'
$payload = if ($Health) { @{ operation = 'health' } } else { @{ operation = 'search'; query = $Query } }
$json = $payload | ConvertTo-Json -Compress
$oldEncoding = $OutputEncoding
try {
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $json | ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes ms@192.168.43.150 python3 /opt/gradheat/search/gradheat_search.py --stdin
    $resultCode = $LASTEXITCODE
} finally { $OutputEncoding = $oldEncoding }
exit $resultCode
