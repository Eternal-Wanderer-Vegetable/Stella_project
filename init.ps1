param([ValidateSet('docs', 'python', 'dashboard')][string]$Mode = 'docs')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python scripts/check_docs.py
    if ($LASTEXITCODE -ne 0) { throw 'Documentation check failed.' }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Diff whitespace check failed.' }
    if ($Mode -eq 'python') {
        python -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'Ruff check failed.' }
        python -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    }
    if ($Mode -eq 'dashboard') {
        pnpm --dir dashboard test
        if ($LASTEXITCODE -ne 0) { throw 'Dashboard tests failed.' }
        pnpm --dir dashboard build
        if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed.' }
    }
    Write-Output "Verification passed for mode: $Mode. Apply additional task gates from docs/agent/verification.md."
} finally {
    Pop-Location
}
