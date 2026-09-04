$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Requirements = Join-Path $ProjectRoot 'embedding-service\requirements.txt'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Python virtual environment (exit code $LASTEXITCODE)."
    }
}

& $VenvPython -m pip --version
if ($LASTEXITCODE -ne 0) {
    throw "pip is unavailable in the virtual environment (exit code $LASTEXITCODE)."
}
& $VenvPython -m pip install --disable-pip-version-check -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install embedding requirements (exit code $LASTEXITCODE)."
}
& $VenvPython -c "import sentence_transformers; print('sentence-transformers:', sentence_transformers.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw 'sentence-transformers import verification failed.'
}

Write-Host 'Embedding Python environment is ready.' -ForegroundColor Green
Write-Host 'Model weights are not downloaded by this script while offline mode is enabled.'
