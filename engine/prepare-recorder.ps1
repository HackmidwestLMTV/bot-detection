# Verify the shared path already included in the integrated checkout.
# Kept as a compatibility entrypoint for older local setup instructions.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $repoRoot 'web/static/path.js'
if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
    throw 'web/static/path.js is missing; restore it from the same reviewed revision as the engine.'
}
Write-Output 'Recorder path.js is ready in the integrated checkout.'
