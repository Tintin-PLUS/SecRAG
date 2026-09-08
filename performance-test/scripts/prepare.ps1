param()

$ErrorActionPreference = 'Stop'
$performanceDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $performanceDir '..')).Path
$localKbTauri = Join-Path $repoRoot 'local-kb\src-tauri'
$embeddingTest = Join-Path $repoRoot 'embedding-test'
$embeddingPython = Join-Path $embeddingTest '.venv\Scripts\python.exe'

Push-Location $repoRoot
try {
    & $embeddingPython -m unittest discover -s performance-test/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'performance-test Python tests failed' }

    & $embeddingPython -m unittest discover -s embedding-test/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'embedding service Python tests failed' }

    & $embeddingPython -m py_compile performance-test/scripts/benchmark_utils.py performance-test/scripts/run_suite.py performance-test/scripts/retest_suite.py performance-test/scripts/single_retrieval.py performance-test/scripts/validate_session.py performance-test/scripts/generate_retest_report.py embedding-test/scripts/embed_server.py
    if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed' }

    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $performanceDir 'scripts\monitor_processes.ps1'),
        [ref]$null,
        [ref]$parseErrors
    ) | Out-Null
    if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
    foreach ($scriptName in @('run_formal_tests.ps1', 'run_single_test.ps1')) {
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $performanceDir $scriptName),
            [ref]$null,
            [ref]$parseErrors
        ) | Out-Null
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
    }
}
finally {
    Pop-Location
}

Push-Location $localKbTauri
try {
    cargo test --locked --bin storage_benchmark
    if ($LASTEXITCODE -ne 0) { throw 'storage benchmark unit tests failed' }
    cargo test --locked --test storage_benchmark_cli
    if ($LASTEXITCODE -ne 0) { throw 'storage benchmark CLI test failed' }
    cargo test --locked --test functional_verification_cli
    if ($LASTEXITCODE -ne 0) { throw 'functional verification CLI test failed' }
    cargo build --locked --release --bin storage_benchmark --bin functional_verification
    if ($LASTEXITCODE -ne 0) { throw 'local-kb release binaries failed to build' }
}
finally {
    Pop-Location
}

Push-Location $embeddingTest
try {
    cargo build --locked --release
    if ($LASTEXITCODE -ne 0) { throw 'embedding-test release binary failed to build' }
}
finally {
    Pop-Location
}

Write-Host 'Preparation complete. Release binaries and test runners are ready.'
