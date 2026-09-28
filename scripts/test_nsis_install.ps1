# Final-EXE installation acceptance harness (WP02 / S02).
#
# Runs one built NSIS installer end to end on a disposable Windows machine
# (hosted runner or test VM) and verifies what actually landed on disk - not
# what the build hoped would land. The golden rules:
#
#   * The EXE is launched silently (/S) with an explicit argument list.
#     /D= must be the LAST argument and must never be quoted (NSIS grammar).
#   * Product self-checks run with the BUNDLED python.exe from outside the
#     repo - never the runner's Python, never with the repo on PYTHONPATH.
#   * "Install finished" means the declared payload actually works: for
#     offline bundles the POSTINSTALL hook must have produced the runtime,
#     the dependency marker, and completed bootstrap progress. A silent
#     exit code alone proves nothing.
#   * Evidence is always collected, also (especially) on failure: report
#     JSON with hashes, timings, per-check results, and the installer's
#     own logs.
#
# Usage:
#   pwsh scripts/test_nsis_install.ps1 -InstallerPath <setup.exe> `
#        -ExpectedPayloadMode offline -ExpectedProfile oneclick-python `
#        -ReportDir <dir>
# Exit code 0 = all checks passed; non-zero = rejected (report still written).

param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [ValidateSet("online", "offline")][string]$ExpectedPayloadMode = "offline",
    [string]$ExpectedProfile = "",
    [string]$ReportDir = "install-report",
    [int]$TimeoutSeconds = 3600,
    [switch]$RequireSigned
)

$ErrorActionPreference = "Stop"
$installer = Resolve-Path $InstallerPath
$reportDir = New-Item -ItemType Directory -Force -Path $ReportDir
$checks = [System.Collections.Generic.List[object]]::new()
$startedAt = [DateTime]::UtcNow

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail = "")
    $script:checks.Add(@{ name = $Name; passed = [bool]$Passed; detail = $Detail })
    $mark = if ($Passed) { "PASS" } else { "FAIL" }
    Write-Host "[$mark] $Name $(if ($Detail) { "- $Detail" })"
}

function Test-PathExists {
    param([string]$Name, [string]$Path)
    $ok = Test-Path -LiteralPath $Path
    Add-Check -Name $Name -Passed $ok -Detail $Path
    return $ok
}

# --- 1. Inventory the artifact under test ---------------------------------
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$sizeBytes = (Get-Item -LiteralPath $installer).Length
Write-Host "Installer: $installer"
Write-Host "SHA-256  : $hash ($sizeBytes bytes)"

# 签名核验（S14）：已签名必须 Valid；RequireSigned（正式发布）时未签名
# 也是失败。签名状态连同 hash 一起进报告，供发布门禁消费。
$signature = Get-AuthenticodeSignature -LiteralPath $installer
$signatureValid = ($signature.Status -eq "Valid")
Add-Check -Name "installer signature" `
    (($signatureValid -or (-not $RequireSigned)) -and $signature.Status -ne "HashMismatch") `
    -Detail "status=$($signature.Status) requireSigned=$RequireSigned"

# --- 2. Install silently into a fixed, space-free directory ---------------
# /D must be last and unquoted (NSIS treats the rest of the command line as
# the target path; quoting would embed literal quotes in the path).
$installDir = Join-Path $env:SystemDrive "stella-install-test"
if (Test-Path -LiteralPath $installDir) {
    Remove-Item -LiteralPath $installDir -Recurse -Force
}
$args = @("/S", "/D=$installDir")
$proc = Start-Process -FilePath $installer -ArgumentList $args -PassThru
if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    $proc.Kill()
    Add-Check -Name "installer exits within timeout" -Passed $false `
        -Detail "killed after $TimeoutSeconds s"
    $exitCode = -1
} else {
    $exitCode = $proc.ExitCode
    Add-Check -Name "installer exit code is 0" -Passed ($exitCode -eq 0) `
        -Detail "exit code $exitCode"
}
$durationSeconds = [int]([DateTime]::UtcNow - $startedAt).TotalSeconds

# --- 3. Verify the installed program tree ---------------------------------
$stella = Join-Path $installDir "resources\stella"
$treeOk = Test-PathExists "program tree staged" (Join-Path $stella "bot.py")

$profilePath = Join-Path $stella ".stella-profile"
$declaredProfile = ""
if (Test-Path -LiteralPath $profilePath) {
    $declaredProfile = (Get-Content $profilePath -Raw).Trim()
}
if ($ExpectedProfile -ne "") {
    Add-Check "staged profile matches expectation" `
        ($declaredProfile -eq $ExpectedProfile) `
        "declared=$declaredProfile expected=$ExpectedProfile"
}

$modePath = Join-Path $stella ".stella-payload-mode"
$declaredMode = ""
if (Test-Path -LiteralPath $modePath) {
    $declaredMode = (Get-Content $modePath -Raw).Trim()
}
Add-Check "payload mode declaration matches expectation" `
    ($declaredMode -eq $ExpectedPayloadMode) `
    "declared=$declaredMode expected=$ExpectedPayloadMode"

$metaPath = Join-Path $stella ".stella-release-metadata.json"
if (Test-Path -LiteralPath $metaPath) {
    $meta = Get-Content $metaPath -Raw | ConvertFrom-Json
    Add-Check "release metadata payload_mode consistent" `
        ($meta.payload_mode -eq $ExpectedPayloadMode) "meta=$($meta.payload_mode)"
    $catalogPath = Join-Path $stella "package-catalog-windows-amd64.json"
    if ($meta.catalog_sha256 -and (Test-Path -LiteralPath $catalogPath)) {
        $catalogHash = (Get-FileHash -LiteralPath $catalogPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Add-Check "bundled catalog hash matches release metadata" `
            ($catalogHash -eq $meta.catalog_sha256.ToLowerInvariant())
    }
} else {
    Add-Check "release metadata present" -Passed $false `
        "missing .stella-release-metadata.json (pre-contract build?)"
}

# --- 4. Offline bundles: the install hook must have done the heavy lifting -
$bundledPython = Join-Path $stella "runtime\python.exe"
if ($ExpectedPayloadMode -eq "offline") {
    Test-PathExists "offline: embedded python extracted" $bundledPython | Out-Null
    Test-PathExists "offline: dependency ready marker" `
        (Join-Path $stella "runtime\.stella-deps-ready") | Out-Null

    # Locate the data root the installer actually used (config.home resolves
    # it independently; do not assume, scan for the progress file).
    $progress = Get-ChildItem -LiteralPath $installDir -Recurse -Filter `
        ".bootstrap-progress" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($progress) {
        $progressPayload = Get-Content $progress.FullName -Raw | ConvertFrom-Json
        Add-Check "offline: bootstrap progress state is complete" `
            ($progressPayload.state -eq "complete") "state=$($progressPayload.state)"
        $dataRoot = $progress.Directory.Parent.FullName
        Test-PathExists "offline: napcat metadata written" `
            (Join-Path $dataRoot ".stella\napcat.json") | Out-Null
    } else {
        Add-Check "offline: bootstrap progress file found" -Passed $false `
            "POSTINSTALL component bootstrap left no progress record"
    }
}

# --- 5. Self-check with the bundled python, outside the repo --------------
# Strip PYTHONPATH so nothing from a checkout can leak into the import set.
if (Test-Path -LiteralPath $bundledPython) {
    $env:PYTHONPATH = ""
    $versionOut = & $bundledPython -c "import sys; print(sys.version.split()[0])" 2>&1
    Add-Check "bundled python runs" ($LASTEXITCODE -eq 0) "version=$versionOut"

    if ($ExpectedPayloadMode -eq "offline") {
        Push-Location $stella
        try {
            $importProbe = & $bundledPython -c `
                "import astrbot_compat, config, core, memory, deploy; print('imports ok')" 2>&1
            $importOut = $importProbe -join " "
            Add-Check "offline: core modules import with bundled python" `
                ($LASTEXITCODE -eq 0) $importOut
        } finally {
            Pop-Location
        }
    }
} elseif ($ExpectedPayloadMode -eq "offline") {
    Add-Check "bundled python runs" -Passed $false "no runtime\python.exe in offline install"
}
# Online variants: the GUI first-boot bootstrap is interactive by design and
# is NOT exercised here; this harness only proves the EXE installs cleanly.
# GUI-boot acceptance belongs to the dedicated VM matrix (plan S15).

# --- 6. Always collect evidence -------------------------------------------
$progressCopy = Get-ChildItem -LiteralPath $installDir -Recurse -Filter `
    ".bootstrap-progress" -ErrorAction SilentlyContinue |
    ForEach-Object { Get-Content $_.FullName -Raw }
$napcatLog = Join-Path $installDir "resources\StellaData\.stella\logs\napcat-msi-install.log"
$napcatLogContent = if (Test-Path -LiteralPath $napcatLog) {
    Get-Content $napcatLog -Raw
} else { "" }

$finishedAt = [DateTime]::UtcNow
$allPassed = ($checks | Where-Object { -not $_.passed } | Measure-Object).Count -eq 0
$report = [ordered]@{
    schema_version   = 1
    status           = if ($allPassed) { "pass" } else { "fail" }
    installer        = $installer.Path
    installer_sha256 = $hash
    installer_size   = $sizeBytes
    signature_status = $signature.Status
    exit_code        = $exitCode
    duration_seconds = $durationSeconds
    expected_profile = $ExpectedProfile
    expected_payload = $ExpectedPayloadMode
    declared_profile = $declaredProfile
    declared_payload = $declaredMode
    checks           = $checks
    progress_snapshot = $progressCopy
    napcat_msi_log_tail = if ($napcatLogContent.Length -gt 4000) {
        $napcatLogContent.Substring($napcatLogContent.Length - 4000)
    } else { $napcatLogContent }
}
$reportPath = Join-Path $reportDir.FullName "install-test-report.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host "Report: $reportPath"

if (-not $allPassed) {
    Write-Host "::error::installation acceptance FAILED for $installer"
    exit 1
}
exit 0
