[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][string]$Query,
    [ValidateRange(1, 50)][int]$Limit = 8,
    [ValidateSet('and', 'or', 'phrase', 'exact')][string]$Mode = 'and'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$matches[0].paths.index)))
& $python -m offline_rag.bm25 query --database $database --query $Query --limit $Limit --mode $Mode
if ($LASTEXITCODE -ne 0) { throw 'Documentation query failed.' }
