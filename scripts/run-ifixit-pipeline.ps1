[CmdletBinding()]
param(
    [string]$DatasetId = 'ifixit-english-2025-12',
    [string]$Source,
    [ValidateRange(256, 20000)][int]$MaxChars = 3200,
    [ValidateRange(1, 1000000)][int]$MaxGuides,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$registryPath = Join-Path $root 'config\datasets.json'
$registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$dataset = $matches[0]
if ([string]$dataset.acquisition.method -ne 'http') { throw 'The iFixit pipeline requires a registered resumable HTTP archive.' }

$raw = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.raw)))
$archiveName = [System.IO.Path]::GetFileName(([uri]$dataset.acquisition.location).AbsolutePath)
$sourcePath = if ($Source) { [System.IO.Path]::GetFullPath($Source) } else { Join-Path $raw $archiveName }
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$runtime = Join-Path $root "runtime\ifixit-$DatasetId"
New-Item -ItemType Directory -Force -Path $raw, (Split-Path -Parent $processed), (Split-Path -Parent $database), $runtime | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'

if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    if ($Source) { throw "iFixit ZIM source not found: $sourcePath" }
    & $python -m offline_rag.acquisition --registry $registryPath --dataset $DatasetId --project-root $root 2>&1 |
        Tee-Object -FilePath (Join-Path $runtime 'acquire.log')
    if ($LASTEXITCODE -ne 0) { throw 'iFixit acquisition failed.' }
}

$importArguments = @(
    '-m', 'offline_rag.ifixit',
    '--source', $sourcePath,
    '--output', $processed,
    '--corpus', $DatasetId,
    '--source-version', ([string]$dataset.release),
    '--max-chars', $MaxChars
)
if ($PSBoundParameters.ContainsKey('MaxGuides')) { $importArguments += @('--max-guides', $MaxGuides) }
if ($Force) { $importArguments += '--force' }
& $python @importArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'import.log')
if ($LASTEXITCODE -ne 0) { throw 'iFixit structured import failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($PSBoundParameters.ContainsKey('MaxGuides')) { $indexArguments += '--allow-incomplete' }
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'index.log')
if ($LASTEXITCODE -ne 0) { throw 'iFixit BM25 indexing failed.' }

Write-Output "Source ZIM: $sourcePath"
Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
