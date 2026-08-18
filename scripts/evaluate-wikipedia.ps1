[CmdletBinding()]
param(
    [ValidateRange(100, 1000000)][int]$PilotArticles = 10000,
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [switch]$Pilot
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$databaseName = if ($Pilot) { "enwiki-$DumpDate-pilot-$PilotArticles.sqlite3" } else { "enwiki-$DumpDate-full.sqlite3" }
$suiteName = if ($Pilot) { 'wikipedia-pilot.json' } else { 'wikipedia-full-v2.json' }
$outputName = if ($Pilot) { "enwiki-$DumpDate-pilot-$PilotArticles-bm25.json" } else { "enwiki-$DumpDate-full-bm25.json" }
$database = Join-Path $root "indexes\wikipedia\$databaseName"
$suite = Join-Path $root "rag\eval\$suiteName"
$output = Join-Path $root "results\rag\$outputName"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
& $python -m offline_rag.evaluate --database $database --suite $suite --output $output
