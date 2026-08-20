[CmdletBinding()]
param(
    [string]$Snapshot = '2026-08-19',
    [ValidateRange(256, 20000)][int]$MaxChars = 3200,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq 'iana-protocol-registries' })
if ($matches.Count -ne 1) { throw 'IANA dataset registry entry is missing or duplicated.' }
$dataset = $matches[0]
$expectedRelease = "snapshot-$Snapshot"
if ([string]$dataset.release -ne $expectedRelease) {
    throw "Registry release '$($dataset.release)' does not match requested snapshot '$expectedRelease'."
}
$source = Join-Path $root "corpora\raw\structured\iana\snapshot-$Snapshot"
$processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$runtime = Join-Path $root 'runtime\iana-protocol-registries'
foreach ($required in @($python, (Join-Path $source 'snapshot-manifest.json'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file not found: $required" }
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processed), (Split-Path -Parent $database), $runtime | Out-Null
$importArguments = @(
    '-m', 'offline_rag.iana',
    '--source-root', $source,
    '--output', $processed,
    '--source-version', $expectedRelease,
    '--license', ([string]$dataset.license),
    '--max-chars', $MaxChars
)
if ($Force) { $importArguments += '--force' }
& $python @importArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'import.log')
if ($LASTEXITCODE -ne 0) { throw 'IANA registry import failed.' }

$indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
if ($Force) { $indexArguments += '--overwrite' }
& $python @indexArguments 2>&1 | Tee-Object -FilePath (Join-Path $runtime 'index.log')
if ($LASTEXITCODE -ne 0) { throw 'IANA BM25 indexing failed.' }

Write-Output "Processed corpus: $processed"
Write-Output "BM25 database: $database"
