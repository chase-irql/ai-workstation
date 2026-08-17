[CmdletBinding()]
param(
    [ValidateRange(100, 1000000)][int]$PilotArticles = 10000,
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-pilot-$PilotArticles.sqlite3"
$suite = Join-Path $root 'rag\eval\wikipedia-pilot.json'
$output = Join-Path $root "results\rag\enwiki-$DumpDate-pilot-$PilotArticles-bm25.json"
& $python -m offline_rag.evaluate --database $database --suite $suite --output $output
