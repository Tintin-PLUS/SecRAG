param(
    [Parameter(Mandatory = $true)][int]$ChunkSize,
    [Parameter(Mandatory = $true)][int]$Overlap,
    [ValidateSet('bge-small', 'm3e-base', 'bge-m3')][string]$Model = 'bge-small',
    [int]$TopK = 5,
    [int]$Rounds = 3,
    [int]$RequestsPerRound = 334,
    [int]$Warmup = 30,
    [int]$BuildRepetitions = 3,
    [int]$Threads = 0,
    [string]$OutputDir = ''
)

$ErrorActionPreference = 'Stop'
$performanceDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $performanceDir '..')).Path
$python = Join-Path $repoRoot 'embedding-test\.venv\Scripts\python.exe'
$arguments = @(
    'performance-test/scripts/single_retrieval.py',
    '--chunk-size', $ChunkSize,
    '--overlap', $Overlap,
    '--model', $Model,
    '--top-k', $TopK,
    '--rounds', $Rounds,
    '--requests-per-round', $RequestsPerRound,
    '--warmup', $Warmup,
    '--build-repetitions', $BuildRepetitions
)
if ($Threads -gt 0) { $arguments += @('--threads', $Threads) }
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) { $arguments += @('--output-dir', $OutputDir) }

Push-Location $repoRoot
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'single retrieval benchmark failed' }
}
finally {
    Pop-Location
}
