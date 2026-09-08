param(
    [Parameter(Mandatory = $true)][string]$PidList,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$StopFile,
    [int]$IntervalMs = 500,
    [int]$MaxSamples = 0,
    [string]$ReadyFile = ''
)

$ErrorActionPreference = 'Stop'
$processIds = $PidList.Split(',') | ForEach-Object { [int]$_.Trim() }
$samples = [System.Collections.Generic.List[object]]::new()
$sampleIndex = 0
if (-not [string]::IsNullOrWhiteSpace($ReadyFile)) {
    New-Item -ItemType File -Path $ReadyFile -Force | Out-Null
}

while (-not (Test-Path -LiteralPath $StopFile)) {
    $capturedAt = [DateTimeOffset]::Now.ToString('o')
    foreach ($processId in $processIds) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            $samples.Add([pscustomobject]@{
                sample_index = $sampleIndex
                captured_at = $capturedAt
                pid = $processId
                process_name = $process.ProcessName
                cpu_seconds = [double]$process.CPU
                working_set_bytes = [long]$process.WorkingSet64
                private_bytes = [long]$process.PrivateMemorySize64
            })
        }
    }
    $sampleIndex++
    if ($MaxSamples -gt 0 -and $sampleIndex -ge $MaxSamples) {
        break
    }
    Start-Sleep -Milliseconds $IntervalMs
}

$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$temporary = "$OutputPath.tmp"
$json = if ($samples.Count -eq 0) { '[]' } else { $samples | ConvertTo-Json -Depth 4 }
Set-Content -LiteralPath $temporary -Value $json -Encoding utf8
Move-Item -LiteralPath $temporary -Destination $OutputPath -Force
