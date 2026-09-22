# Launch the pinned official CLI with existing project credentials in process scope only.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$credentialPath = Join-Path $projectRoot '.claude/settings.local.json'
$previousKey = $env:FIRECRAWL_API_KEY
$previousSearchFeedback = $env:FIRECRAWL_NO_SEARCH_FEEDBACK
$previousEndpointFeedback = $env:FIRECRAWL_NO_ENDPOINT_FEEDBACK
try {
    if (-not $env:FIRECRAWL_API_KEY -and (Test-Path -LiteralPath $credentialPath)) {
        $config = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
        $env:FIRECRAWL_API_KEY = $config.env.FIRECRAWL_API_KEY
    }
    $env:FIRECRAWL_NO_SEARCH_FEEDBACK = '1'
    $env:FIRECRAWL_NO_ENDPOINT_FEEDBACK = '1'
    $cli = Join-Path $env:USERPROFILE '.codex/tools/gradheat-firecrawl/node_modules/firecrawl-cli/dist/index.js'
    if (-not (Test-Path -LiteralPath $cli)) { throw 'Pinned Firecrawl CLI is not installed.' }
    & node $cli @args
    $resultCode = $LASTEXITCODE
} finally {
    $env:FIRECRAWL_API_KEY = $previousKey
    $env:FIRECRAWL_NO_SEARCH_FEEDBACK = $previousSearchFeedback
    $env:FIRECRAWL_NO_ENDPOINT_FEEDBACK = $previousEndpointFeedback
}
exit $resultCode
