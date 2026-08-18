[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$runtime = Join-Path $root 'runtime\wikipedia-full'
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\full"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"

$allProcesses = Get-CimInstance Win32_Process
$processes = $allProcesses | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.CommandLine -match 'run-wikipedia-full\.ps1|offline_rag\.wikipedia_(dump|multistream)|offline_rag\.bm25 build'
}
$processIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($process in $processes) { [void]$processIds.Add([int]$process.ProcessId) }
do {
    $previousCount = $processIds.Count
    foreach ($process in $allProcesses) {
        if ($processIds.Contains([int]$process.ParentProcessId)) {
            [void]$processIds.Add([int]$process.ProcessId)
        }
    }
} while ($processIds.Count -gt $previousCount)
$processes = $allProcesses | Where-Object { $processIds.Contains([int]$_.ProcessId) }
$disk = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).TrimEnd(':\'))
$files = @()
$parts = Join-Path $processed 'parts'
if (Test-Path -LiteralPath $parts -PathType Container) {
    $files += Get-ChildItem -LiteralPath $parts -File
}
if (Test-Path -LiteralPath $database -PathType Leaf) { $files += Get-Item -LiteralPath $database }
$partCount = @($files | Where-Object { $_.Name -like '*.manifest.json' }).Count

[pscustomobject]@{
    RunningProcesses = @($processes).Count
    ProcessIds = (@($processes.ProcessId) -join ', ')
    FreeGiB = [math]::Round($disk.Free / 1GB, 1)
    OutputGiB = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1GB, 3)
    CompletedParts = $partCount
    Stage = if (@($processes | Where-Object { $_.CommandLine -match 'offline_rag\.bm25 build' }).Count) { 'BM25 indexing' } elseif (Test-Path -LiteralPath $database) { 'BM25 complete' } elseif (Test-Path -LiteralPath $parts) { 'Parallel extraction' } else { 'Not started' }
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
