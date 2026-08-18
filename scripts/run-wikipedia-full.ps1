[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateRange(1, 20)][int]$Workers = 8,
    [ValidateRange(1, 1024)][int]$BatchBlocks = 128,
    [ValidateRange(1, 128)][int]$TargetPartMiB = 8,
    [ValidateRange(1, 19)][int]$ZstdLevel = 3,
    [ValidateRange(5, 50)][int]$MinimumFreePercent = 15,
    [switch]$Resume,
    [switch]$QuickResume,
    [switch]$ExtractionOnly
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run the RAG virtual-environment setup first.' }

$env:PYTHONPATH = Join-Path $root 'rag\src'
$archive = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate\enwiki-$DumpDate-pages-articles-multistream.xml.bz2"
$index = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate\enwiki-$DumpDate-pages-articles-multistream-index.txt.bz2"
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\full"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$runtime = Join-Path $root 'runtime\wikipedia-full'
$extractLog = Join-Path $runtime 'extract.log'
$indexLog = Join-Path $runtime 'index.log'

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "Wikipedia archive not found: $archive" }
if (-not (Test-Path -LiteralPath $index -PathType Leaf)) { throw "Wikipedia multistream index not found: $index" }
if ($Resume -and -not (Test-Path -LiteralPath (Join-Path $processed 'multistream-plan.json'))) {
    throw "Resume plan not found under: $processed"
}
if (-not $Resume -and (Test-Path -LiteralPath $processed)) { throw "Full extraction output already exists: $processed" }
if (Test-Path -LiteralPath $database) { throw "Full BM25 database already exists: $database" }

New-Item -ItemType Directory -Force -Path $processed, (Split-Path -Parent $database), $runtime | Out-Null

try {
    $extractArguments = @(
        '-m', 'offline_rag.wikipedia_multistream',
        '--archive', $archive,
        '--index', $index,
        '--output', $processed,
        '--dump-date', $DumpDate,
        '--workers', $Workers,
        '--batch-blocks', $BatchBlocks,
        '--target-part-mib', $TargetPartMiB,
        '--zstd-level', $ZstdLevel
    )
    if ($Resume) { $extractArguments += '--resume' }
    if ($QuickResume) { $extractArguments += '--quick-resume' }
    & $python @extractArguments 2>&1 | Tee-Object -FilePath $extractLog
    if ($LASTEXITCODE -ne 0) { throw 'Full Wikipedia extraction failed.' }

    $stats = Get-Content -Raw -LiteralPath (Join-Path $processed 'extraction-stats.json') | ConvertFrom-Json
    if (-not $stats.completed -or $stats.stop_reason -ne 'archive_complete') {
        throw "Extraction did not complete the archive: $($stats.stop_reason)"
    }
    $minimumFree = [double]$stats.storage_projection.disk_total_bytes * ($MinimumFreePercent / 100.0)
    if ([double]$stats.storage_projection.projected_free_after_build_bytes -lt $minimumFree) {
        throw "Storage gate blocked indexing: projected free space would be below $MinimumFreePercent percent."
    }

    if ($ExtractionOnly) {
        Write-Output "Full Wikipedia shards: $processed"
        return
    }

    & $python -m offline_rag.bm25 build --input $processed --database $database `
        2>&1 | Tee-Object -FilePath $indexLog
    if ($LASTEXITCODE -ne 0) { throw 'Full Wikipedia BM25 indexing failed.' }

    Write-Output "Full Wikipedia database: $database"
}
catch {
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $runtime 'failure.log')
    throw
}
