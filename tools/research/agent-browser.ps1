# Version-pinned, user-local binary; no system Node or PATH changes.
$binaryRoot = Join-Path $env:USERPROFILE '.codex/tools/gradheat-agent-browser/0.38.1'
$binary = Join-Path $binaryRoot 'agent-browser.exe'
if (-not (Test-Path -LiteralPath $binary)) { throw "Missing agent-browser: $binary" }
$oldSkillsDir = $env:AGENT_BROWSER_SKILLS_DIR
try {
    $env:AGENT_BROWSER_SKILLS_DIR = Join-Path $binaryRoot 'skill-data'
    & $binary @args
    $toolExit = $LASTEXITCODE
} finally {
    $env:AGENT_BROWSER_SKILLS_DIR = $oldSkillsDir
}
exit $toolExit
