#requires -Version 5.1
$ErrorActionPreference = 'Stop'

$coreScript = Join-Path $PSScriptRoot 'sync_test_repo.py'
$python = Get-Command python -ErrorAction SilentlyContinue

if ($null -ne $python) {
    & python $coreScript
} else {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $launcher) {
        [Console]::Error.WriteLine('Python 3 is required to sync this test checkout.')
        exit 127
    }
    & py -3 $coreScript
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
