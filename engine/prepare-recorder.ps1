# Copy the platform's unchanged path implementation for local-only use.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $pathSource = git show origin/p1-platform:web/static/path.js
    if ($LASTEXITCODE -ne 0) { throw 'origin/p1-platform:web/static/path.js is unavailable' }
    $destination = Join-Path $repoRoot 'web/static/path.js'
    if (Test-Path -LiteralPath $destination) {
        if (((Get-Content -LiteralPath $destination) -join "`n") -ne ($pathSource -join "`n")) {
            throw 'Existing path.js differs; refusing to overwrite it'
        }
    } else {
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        [IO.File]::WriteAllText($destination, ($pathSource -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    }
    $exclude = git rev-parse --git-path info/exclude
    $ignoreLine = '/web/static/path.js'
    if (-not (Test-Path -LiteralPath $exclude) -or -not ((Get-Content -LiteralPath $exclude) -contains $ignoreLine)) {
        Add-Content -LiteralPath $exclude -Value "`n$ignoreLine"
    }
    Write-Output 'Local recorder path.js is ready (excluded from commits).'
} finally { Pop-Location }
