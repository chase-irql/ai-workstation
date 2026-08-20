[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [ValidateRange(1, 512)][int]$BatchSize = 128,
    [ValidateRange(1, 8)][int]$EmbeddingWorkers = 2,
    [ValidateRange(1, 1000000)][int]$CheckpointInterval = 4096,
    [ValidateRange(256, 16000)][int]$MaxCharacters = 4000,
    [string]$ModelId,
    [string]$ReuseFrom,
    [switch]$Resume,
    [switch]$Restart,
    [switch]$Force,
    [switch]$SkipReuseChecksums,
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
foreach ($required in @($python, $models, $database)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file not found: $required" }
}
$env:PYTHONPATH = Join-Path $root 'rag\src'
$arguments = @(
    '-m', 'offline_rag.chunk_vector_index', 'build',
    '--database', $database,
    '--output', $semantic,
    '--models', $models,
    '--batch-size', $BatchSize,
    '--embedding-workers', $EmbeddingWorkers,
    '--checkpoint-interval', $CheckpointInterval,
    '--max-characters', $MaxCharacters
)
if ($ModelId) { $arguments += @('--model-id', $ModelId) }
if ($ReuseFrom) {
    $reusePath = if ([System.IO.Path]::IsPathRooted($ReuseFrom)) { $ReuseFrom } else { Join-Path $root $ReuseFrom }
    $arguments += @('--reuse-from', [System.IO.Path]::GetFullPath($reusePath))
}
if ($SkipReuseChecksums) { $arguments += '--skip-reuse-checksums' }
if ($Resume) { $arguments += '--resume' }
if ($Restart) { $arguments += '--restart' }
if ($Force) { $arguments += '--overwrite' }

try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Chunk semantic build failed for '$DatasetId'." }
    & $python -m offline_rag.chunk_vector_index verify --index $semantic --database $database
    if ($LASTEXITCODE -ne 0) { throw "Chunk semantic verification failed for '$DatasetId'." }
}
finally {
    if ($Unload) {
        $modelRegistry = Get-Content -LiteralPath $models -Raw | ConvertFrom-Json
        $selected = if ($ModelId) {
            $modelRegistry.models | Where-Object { $_.id -eq $ModelId -and $_.role -eq 'embedding' } | Select-Object -First 1
        } else {
            $modelRegistry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
        }
        if ($selected -and (Get-Command ollama -ErrorAction SilentlyContinue)) {
            & ollama stop ([string]$selected.ollama_model) | Out-Null
        }
    }
}
