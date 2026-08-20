[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [string]$Source,
    [ValidateRange(128, 20000)][int]$MaxChars = 3200,
    [ValidateRange(0, 20000)][int]$MinChars = 300,
    [ValidateRange(0.0, 1.0)][double]$MinSearchableRatio = 0.5,
    [ValidateSet('layout', 'plain')][string]$ExtractionMode,
    [ValidateRange(1, 1000000)][int]$MaxFiles,
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
$sourceCandidate = if ($Source) {
    $Source
} elseif ([string]$dataset.acquisition.method -in @('http-file-set', 'http-catalog-file-set')) {
    Join-Path (Join-Path $root ([string]$dataset.paths.raw)) 'files'
} else {
    Join-Path $root ([string]$dataset.paths.raw)
}
$sourcePath = [System.IO.Path]::GetFullPath($sourceCandidate)
if (-not (Test-Path -LiteralPath $sourcePath)) { throw "PDF source file or directory not found: $sourcePath" }
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$runtime = Join-Path $root "runtime\pdf-manual-$DatasetId"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processed), (Split-Path -Parent $database), $runtime | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'
$resolvedExtractionMode = if ($ExtractionMode) {
    $ExtractionMode
} elseif ($dataset.ingestion -and $dataset.ingestion.PSObject.Properties.Name -contains 'pdf_text_extraction_mode') {
    [string]$dataset.ingestion.pdf_text_extraction_mode
} else {
    'layout'
}

$importArguments = @(
    '-m', 'offline_rag.pdf_manuals',
    '--source', $sourcePath,
    '--output', $processed,
    '--corpus', $DatasetId,
    '--source-version', ([string]$dataset.release),
    '--license', ([string]$dataset.license),
    '--base-url', ([string]$dataset.official_source_url),
    '--max-chars', $MaxChars,
    '--min-chars', $MinChars,
    '--min-searchable-ratio', $MinSearchableRatio.ToString([Globalization.CultureInfo]::InvariantCulture)
    '--extraction-mode', $resolvedExtractionMode
)
if ($dataset.acquisition.PSObject.Properties.Name -contains 'source_url_template') {
    $importArguments += @('--source-url-template', ([string]$dataset.acquisition.source_url_template))
}
if ($dataset.PSObject.Properties.Name -contains 'source_timestamp') {
    $importArguments += @('--source-timestamp', ([string]$dataset.source_timestamp))
}
if ($dataset.ingestion -and $dataset.ingestion.PSObject.Properties.Name -contains 'title_overrides') {
    $overridesPath = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.ingestion.title_overrides)))
    $rootPrefix = [System.IO.Path]::GetFullPath($root).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $overridesPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Title overrides path escapes the project root: $overridesPath"
    }
    if (-not (Test-Path -LiteralPath $overridesPath -PathType Leaf)) {
        throw "Title overrides file not found: $overridesPath"
    }
    $importArguments += @('--title-overrides', $overridesPath)
} elseif ($dataset.ingestion -and $dataset.ingestion.PSObject.Properties.Name -contains 'title_overrides_from_acquisition' -and [bool]$dataset.ingestion.title_overrides_from_acquisition) {
    $overridesPath = Join-Path (Join-Path $root ([string]$dataset.paths.raw)) 'acquisition-title-overrides.json'
    $overridesPath = [System.IO.Path]::GetFullPath($overridesPath)
    if (-not (Test-Path -LiteralPath $overridesPath -PathType Leaf)) {
        throw "Acquisition-derived title overrides file not found: $overridesPath"
    }
    $importArguments += @('--title-overrides', $overridesPath)
}
if ($PSBoundParameters.ContainsKey('MaxFiles')) { $importArguments += @('--max-files', $MaxFiles) }
if ($Force) { $importArguments += '--force' }
& $python @importArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'import.log')
if ($LASTEXITCODE -ne 0) { throw 'PDF manual import failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($PSBoundParameters.ContainsKey('MaxFiles')) { $indexArguments += '--allow-incomplete' }
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'index.log')
if ($LASTEXITCODE -ne 0) { throw 'PDF manual BM25 indexing failed.' }

Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
