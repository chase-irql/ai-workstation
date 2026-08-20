[CmdletBinding()]
param(
    [string]$DatasetId = 'devops-stackexchange',
    [ValidateRange(128, 20000)][int]$MaxChars = 3200,
    [ValidateRange(0, 20000)][int]$MinChars = 300,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$dataset = $matches[0]
$source = [System.IO.Path]::GetFullPath((Join-Path $root (Join-Path ([string]$dataset.paths.raw) 'extracted')))
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$runtime = Join-Path $root "runtime\stack-exchange-$DatasetId"
if (-not (Test-Path -LiteralPath (Join-Path $source 'Posts.xml') -PathType Leaf)) {
    throw "Extracted Stack Exchange Posts.xml not found: $source"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processed), (Split-Path -Parent $database), $runtime | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'

$importArguments = @(
    '-m', 'offline_rag.stack_exchange',
    '--source-root', $source,
    '--output', $processed,
    '--corpus', $DatasetId,
    '--source-version', ([string]$dataset.release),
    '--site-url', ([string]$dataset.official_source_url),
    '--max-chars', $MaxChars,
    '--min-chars', $MinChars
)
if ($Force) { $importArguments += '--force' }
& $python @importArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'import.log')
if ($LASTEXITCODE -ne 0) { throw 'Stack Exchange import failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'index.log')
if ($LASTEXITCODE -ne 0) { throw 'Stack Exchange BM25 indexing failed.' }
& $python -m offline_rag.verify --database $database --input $processed --smoke-query 'Docker Kubernetes deployment'
if ($LASTEXITCODE -ne 0) { throw 'Stack Exchange BM25 verification failed.' }

Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
