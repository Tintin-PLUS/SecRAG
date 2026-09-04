$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Requirements = Join-Path $ProjectRoot 'embedding-service\requirements.txt'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv (Join-Path $ProjectRoot '.venv')
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Requirements
& $VenvPython -c "import sentence_transformers; print('sentence-transformers:', sentence_transformers.__version__)"

Write-Host 'Embedding Python environment is ready.' -ForegroundColor Green
Write-Host 'Model weights are not downloaded by this script while offline mode is enabled.'
