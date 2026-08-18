[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$runtime = Join-Path $root 'runtime\wikipedia-full'
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\full"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"

$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.CommandLine -match 'run-wikipedia-full\.ps1|offline_rag\.wikipedia_dump|offline_rag\.bm25 build'
}
$disk = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).TrimEnd(':\'))
$files = @(
    Join-Path $processed 'documents.jsonl'
    Join-Path $processed 'chunks.jsonl'
    $database
) | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object { Get-Item -LiteralPath $_ }

[pscustomobject]@{
    RunningProcesses = @($processes).Count
    ProcessIds = (@($processes.ProcessId) -join ', ')
    FreeGiB = [math]::Round($disk.Free / 1GB, 1)
    OutputGiB = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1GB, 3)
    Stage = if (Test-Path -LiteralPath $database) { 'BM25 indexing' } elseif (Test-Path -LiteralPath (Join-Path $processed 'chunks.jsonl')) { 'Extraction' } else { 'Not started' }
} | Format-List

$stats = Join-Path $processed 'extraction-stats.json'
if (Test-Path -LiteralPath $stats) {
    Write-Output 'Extraction statistics:'
    Get-Content -LiteralPath $stats
}
else {
    $extractLog = Join-Path $runtime 'extract.log'
    if (Test-Path -LiteralPath $extractLog) {
        Write-Output 'Latest extraction progress:'
        Get-Content -LiteralPath $extractLog -Tail 5
    }
}

$failureLog = Join-Path $runtime 'failure.log'
if (Test-Path -LiteralPath $failureLog) {
    Write-Warning "Failure log present: $failureLog"
    Get-Content -LiteralPath $failureLog -Tail 20
}
