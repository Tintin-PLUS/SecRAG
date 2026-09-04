$ErrorActionPreference = 'Stop'
$BaseUrl = if ($env:LOCAL_KB_EMBEDDING_BASE_URL) { $env:LOCAL_KB_EMBEDDING_BASE_URL.TrimEnd('/') } else { 'http://127.0.0.1:8902' }
$Health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 5
$Models = Invoke-RestMethod -Method Get -Uri "$BaseUrl/v1/models" -TimeoutSec 5

Write-Host "Health: $($Health.status)"
Write-Host "Dependency available: $($Health.dependency_available)"
Write-Host "Offline: $($Health.offline)"
$Models.models | Select-Object model_id, model_name, dimension, normalize, config_hash | Format-Table -AutoSize
