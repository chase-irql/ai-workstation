[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [switch]$Resume
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run the RAG virtual-environment setup first.' }

$env:PYTHONPATH = Join-Path $root 'rag\src'
$archive = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate\enwiki-$DumpDate-pages-articles-multistream.xml.bz2"
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\full"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$runtime = Join-Path $root 'runtime\wikipedia-full'
$extractLog = Join-Path $runtime 'extract.log'
$indexLog = Join-Path $runtime 'index.log'

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "Wikipedia archive not found: $archive" }
if ($Resume -and -not (Test-Path -LiteralPath (Join-Path $processed 'checkpoint.json'))) {
    throw "Resume checkpoint not found under: $processed"
}
if (-not $Resume -and (Test-Path -LiteralPath $processed)) { throw "Full extraction output already exists: $processed" }
if (Test-Path -LiteralPath $database) { throw "Full BM25 database already exists: $database" }

New-Item -ItemType Directory -Force -Path $processed, (Split-Path -Parent $database), $runtime | Out-Null

try {
    $extractArguments = @(
        '-m', 'offline_rag.wikipedia_dump',
        '--archive', $archive,
        '--output', $processed,
        '--dump-date', $DumpDate
    )
    if ($Resume) { $extractArguments += '--resume' }
    & $python @extractArguments 2>&1 | Tee-Object -FilePath $extractLog
    if ($LASTEXITCODE -ne 0) { throw 'Full Wikipedia extraction failed.' }

    & $python -m offline_rag.bm25 build --input $processed --database $database `
        2>&1 | Tee-Object -FilePath $indexLog
    if ($LASTEXITCODE -ne 0) { throw 'Full Wikipedia BM25 indexing failed.' }

    Write-Output "Full Wikipedia database: $database"
}
catch {
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $runtime 'failure.log')
    throw
}
