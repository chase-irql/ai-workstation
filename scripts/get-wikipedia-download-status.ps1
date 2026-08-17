[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$destinationRoot = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate"
$statePath = Join-Path $root "runtime\wikipedia-download\enwiki-$DumpDate-state.json"
$jobName = "Local AI Wikipedia enwiki-$DumpDate"
$expectedBytes = 26952317546L
$filesOnDisk = @(Get-ChildItem -LiteralPath $destinationRoot -File -ErrorAction SilentlyContinue)
$visibleBytes = [long](($filesOnDisk | Measure-Object -Property Length -Sum).Sum)
$bitsJob = Get-BitsTransfer -ErrorAction SilentlyContinue | Where-Object DisplayName -eq $jobName | Select-Object -First 1

[ordered]@{
    captured_at = (Get-Date).ToString('o')
    state = if (Test-Path -LiteralPath $statePath) { Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json } else { $null }
    bits = if ($bitsJob) {
        [ordered]@{
            state = $bitsJob.JobState.ToString()
            bytes_transferred = [long]$bitsJob.BytesTransferred
            bytes_total = [long]$bitsJob.BytesTotal
            percent = if ($bitsJob.BytesTotal -gt 0) { [math]::Round(100 * $bitsJob.BytesTransferred / $bitsJob.BytesTotal, 2) } else { 0 }
        }
    } else { $null }
    visible_bytes = $visibleBytes
    expected_bytes = $expectedBytes
    files = @($filesOnDisk | Select-Object Name, Length, LastWriteTime)
} | ConvertTo-Json -Depth 8
