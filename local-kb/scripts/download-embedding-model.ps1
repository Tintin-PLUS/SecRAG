param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('bge-small', 'm3e-base', 'bge-m3')]
    [string]$Model
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Downloader = Join-Path $ProjectRoot 'embedding-service\download_model.py'
$DirectoryName = switch ($Model) {
    'bge-small' { 'bge-small' }
    'm3e-base' { 'm3e-base' }
    'bge-m3' { 'bge-m3' }
}
$Destination = Join-Path (Join-Path $ProjectRoot 'models') $DirectoryName

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python environment is missing. Run scripts\setup-embedding.ps1 first.'
}

$env:LOCAL_KB_EMBEDDING_OFFLINE = '0'
& $Python $Downloader $Model $Destination

$VariableName = switch ($Model) {
    'bge-small' { 'LOCAL_KB_MODEL_BGE_SMALL' }
    'm3e-base' { 'LOCAL_KB_MODEL_M3E_BASE' }
    'bge-m3' { 'LOCAL_KB_MODEL_BGE_M3' }
}
Write-Host "Model is ready. Add this line to .env:" -ForegroundColor Green
Write-Host "$VariableName=$Destination"
Write-Host 'Keep LOCAL_KB_EMBEDDING_OFFLINE=1 for normal offline runs.'
