[CmdletBinding()]
param(
    [ValidateRange(100, 1000000)][int]$MaxArticles = 10000,
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run the RAG virtual-environment setup first.' }
$env:PYTHONPATH = Join-Path $root 'rag\src'
$archive = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate\enwiki-$DumpDate-pages-articles-multistream.xml.bz2"
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\pilot-$MaxArticles"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-pilot-$MaxArticles.sqlite3"
$runtime = Join-Path $root 'runtime\wikipedia-pilot'
New-Item -ItemType Directory -Force -Path $processed, (Split-Path -Parent $database), $runtime | Out-Null

$extractArguments = @(
    '-m', 'offline_rag.wikipedia_dump',
    '--archive', $archive,
    '--output', $processed,
    '--dump-date', $DumpDate,
    '--max-articles', $MaxArticles
)
if ($Force) { $extractArguments += '--force' }
& $python @extractArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime "extract-$MaxArticles.log")
if ($LASTEXITCODE -ne 0) { throw 'Wikipedia pilot extraction failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime "index-$MaxArticles.log")
if ($LASTEXITCODE -ne 0) { throw 'Wikipedia pilot BM25 indexing failed.' }

Write-Output "Pilot database: $database"
