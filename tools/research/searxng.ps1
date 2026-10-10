param([string]$Query, [switch]$Health)
$ErrorActionPreference = 'Stop'
$connectionPath = Join-Path $PSScriptRoot '../../contracts/runtime-connections.json'
$connection = Get-Content -LiteralPath $connectionPath -Raw | ConvertFrom-Json
$vmAddress = [System.Net.IPAddress]::Parse($connection.vm_host).ToString()
$vmAlias = [System.Net.IPAddress]::Parse($connection.host_key_alias).ToString()
if ($connection.vm_user -notmatch '^[a-z_][a-z0-9_-]*$') { throw 'Invalid VM SSH user' }
$vmTarget = "$($connection.vm_user)@$vmAddress"
$payload = if ($Health) { @{ operation = 'health' } } else { @{ operation = 'search'; query = $Query } }
$json = $payload | ConvertTo-Json -Compress
$oldEncoding = $OutputEncoding
try {
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $json | ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes -o "HostKeyAlias=$vmAlias" $vmTarget python3 /opt/gradheat/search/gradheat_search.py --stdin
    $resultCode = $LASTEXITCODE
} finally { $OutputEncoding = $oldEncoding }
exit $resultCode
