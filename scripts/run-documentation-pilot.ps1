[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][string]$SourceRoot,
    [ValidateRange(128, 20000)][int]$MaxChars = 3200,
    [ValidateRange(0, 20000)][int]$MinChars = 300,
    [ValidateRange(1, 1000000)][int]$MaxFiles,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$source = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Documentation source directory not found: $source" }
$registryPath = Join-Path $root 'config\datasets.json'
$registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$dataset = $matches[0]
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$runtime = Join-Path $root "runtime\documentation-$DatasetId"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processed), (Split-Path -Parent $database), $runtime | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'

$importArguments = @(
    '-m', 'offline_rag.documentation',
    '--source-root', $source,
    '--output', $processed,
    '--corpus', $DatasetId,
    '--source-version', ([string]$dataset.release),
    '--license', ([string]$dataset.license),
    '--base-url', ([string]$dataset.official_source_url),
    '--max-chars', $MaxChars,
    '--min-chars', $MinChars
)
if ($dataset.acquisition.PSObject.Properties.Name -contains 'source_url_template') {
    $importArguments += @('--source-url-template', ([string]$dataset.acquisition.source_url_template))
}
if ($dataset.PSObject.Properties.Name -contains 'ingestion') {
    if ($dataset.ingestion.PSObject.Properties.Name -contains 'content_subdirectory') {
        $importArguments += @('--content-subdirectory', ([string]$dataset.ingestion.content_subdirectory))
    }
    if ($dataset.ingestion.PSObject.Properties.Name -contains 'include_globs') {
        foreach ($pattern in @($dataset.ingestion.include_globs)) {
            $importArguments += @('--include-glob', ([string]$pattern))
        }
    }
    if ($dataset.ingestion.PSObject.Properties.Name -contains 'exclude_globs') {
        foreach ($pattern in @($dataset.ingestion.exclude_globs)) {
            $importArguments += @('--exclude-glob', ([string]$pattern))
        }
    }
}
if ($PSBoundParameters.ContainsKey('MaxFiles')) { $importArguments += @('--max-files', $MaxFiles) }
if ($Force) { $importArguments += '--force' }
& $python @importArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'import.log')
if ($LASTEXITCODE -ne 0) { throw 'Documentation import failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($PSBoundParameters.ContainsKey('MaxFiles')) { $indexArguments += '--allow-incomplete' }
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'index.log')
if ($LASTEXITCODE -ne 0) { throw 'Documentation BM25 indexing failed.' }

Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
