[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Query,
    [ValidateRange(1, 50)][int]$Limit = 8,
    [ValidateSet('and', 'or', 'phrase', 'exact')][string]$Mode = 'and',
    [ValidateRange(100, 1000000)][int]$PilotArticles = 10000,
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-pilot-$PilotArticles.sqlite3"
& $python -m offline_rag.bm25 query --database $database --query $Query --limit $Limit --mode $Mode
