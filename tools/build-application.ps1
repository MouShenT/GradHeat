param([string]$Npm = 'npm.cmd', [string]$Maven = 'mvn.cmd')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $Npm ci --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & $Npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    & $Npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
& $Maven -f (Join-Path $projectRoot 'backend\pom.xml') verify
if ($LASTEXITCODE -ne 0) { throw 'Java build/tests failed.' }
Write-Output 'Application built: frontend is packaged into the Java jar; local outputs stay outside Git.'
