[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][string]$Suite,
    [string]$Output,
    [string]$ModelId,
    [ValidateSet('auto', 'bm25', 'semantic', 'hybrid')][string]$Retrieval = 'auto',
    [switch]$Unload
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$models = Join-Path $root 'config\models.json'
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Dataset '$DatasetId' is missing or duplicated." }
$dataset = $matches[0]
if (-not $dataset.paths.semantic_index) { throw "Dataset '$DatasetId' has no paths.semantic_index." }
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$semantic = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.semantic_index)))
$suiteValue = if ([System.IO.Path]::IsPathRooted($Suite)) { $Suite } else { Join-Path $root $Suite }
$suitePath = [System.IO.Path]::GetFullPath($suiteValue)
if (-not $Output) { $Output = Join-Path $root "results\rag\semantic\$DatasetId-reranked.json" }
$outputValue = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $root $Output }
$outputPath = [System.IO.Path]::GetFullPath($outputValue)
foreach ($required in @($python, $models, $database, (Join-Path $semantic 'manifest.json'), $suitePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file not found: $required" }
}
$env:PYTHONPATH = Join-Path $root 'rag\src'
$arguments = @(
    '-m', 'offline_rag.knowledge_evaluate',
    '--database', $database,
    '--index', $semantic,
    '--suite', $suitePath,
    '--output', $outputPath,
    '--models', $models
    '--retrieval', $Retrieval
)
if ($ModelId) { $arguments += @('--model-id', $ModelId) }
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Reranked evaluation failed for '$DatasetId'." }
}
finally {
    if ($Unload) {
        $modelRegistry = Get-Content -LiteralPath $models -Raw | ConvertFrom-Json
        $selected = if ($ModelId) {
            $modelRegistry.models | Where-Object { $_.id -eq $ModelId -and $_.role -eq 'embedding' } | Select-Object -First 1
        }
        else {
            $modelRegistry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
        }
        if ($selected -and (Get-Command ollama -ErrorAction SilentlyContinue)) {
            & ollama stop ([string]$selected.ollama_model) | Out-Null
        }
    }
}
