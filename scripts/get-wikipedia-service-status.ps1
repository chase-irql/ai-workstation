[CmdletBinding()]
param(
    [string]$ListenAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8765
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$runtime = Join-Path $root 'runtime\wikipedia-service'
$pidPath = Join-Path $runtime 'service.pid'
$recordedPid = $null
$processValid = $false
if (Test-Path -LiteralPath $pidPath) {
    $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
    $processValid = [bool]($process -and $process.CommandLine -match 'offline_rag\.service')
}

try {
    $health = Invoke-RestMethod -Uri "http://$($ListenAddress):$Port/health" -TimeoutSec 3
    $retrieval = if ($health.PSObject.Properties.Name -contains 'retrieval') {
        $health.retrieval
    }
    else {
        [ordered]@{
            default_mode = 'bm25'
            available_modes = @('bm25')
            bm25_ready = $true
            legacy_service = $true
        }
    }
    [ordered]@{
        status = $health.status
        pid = $recordedPid
        process_valid = $processValid
        url = "http://$($ListenAddress):$Port/"
        index = $health.index
        retrieval = $retrieval
    } | ConvertTo-Json -Depth 6
    exit 0
}
catch {
    [ordered]@{
        status = 'stopped'
        pid = $recordedPid
        process_valid = $processValid
        url = "http://$($ListenAddress):$Port/"
        error = $_.Exception.Message
    } | ConvertTo-Json
    exit 1
}
