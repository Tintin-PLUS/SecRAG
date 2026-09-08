param(
    [string]$SessionId = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string]$ConfigPath = ''
)

$ErrorActionPreference = 'Stop'
$performanceDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $performanceDir '..')).Path
$python = Join-Path $repoRoot 'embedding-test\.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $performanceDir 'config\retest.json'
}
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$sessionDir = Join-Path $performanceDir "results\$SessionId"
$reportDir = Join-Path $performanceDir "reports\$SessionId"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment is missing: $python"
}
if ((Test-Path -LiteralPath $sessionDir) -or (Test-Path -LiteralPath $reportDir)) {
    throw "Session or report already exists: $SessionId"
}

Push-Location $repoRoot
try {
    & $python performance-test/scripts/retest_suite.py --config $ConfigPath --session-dir $sessionDir --phase all
    if ($LASTEXITCODE -ne 0) { throw 'benchmark runner failed' }

    & $python performance-test/scripts/validate_session.py --session-dir $sessionDir
    if ($LASTEXITCODE -ne 0) { throw 'session integrity check failed' }

    & $python performance-test/scripts/generate_retest_report.py --session-dir $sessionDir --output-dir $reportDir
    if ($LASTEXITCODE -ne 0) { throw 'report generation failed' }
}
finally {
    Pop-Location
}

Write-Host "Session data: $sessionDir"
Write-Host "Report: $reportDir"
