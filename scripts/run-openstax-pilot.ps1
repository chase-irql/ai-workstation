[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][string]$SourceRoot,
    [ValidateRange(128, 20000)][int]$MaxChars = 3200,
    [ValidateRange(0, 20000)][int]$MinChars = 300,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$source = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "OpenStax source directory not found: $source" }
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$dataset = $matches[0]
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$contentRoot = Join-Path $source ([string]$dataset.ingestion.content_subdirectory)
if (-not (Test-Path -LiteralPath $contentRoot -PathType Container)) { throw "OpenStax content root not found: $contentRoot" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processed), (Split-Path -Parent $database) | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'
$arguments = @(
    '-m', 'offline_rag.openstax',
    '--source-root', $contentRoot,
    '--output', $processed,
    '--corpus', $DatasetId,
    '--source-version', ([string]$dataset.release),
    '--source-url-template', ([string]$dataset.acquisition.source_url_template),
    '--max-chars', $MaxChars,
    '--min-chars', $MinChars
)
if ($Force) { $arguments += '--force' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'OpenStax import failed.' }
$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments
if ($LASTEXITCODE -ne 0) { throw 'OpenStax BM25 indexing failed.' }
Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
