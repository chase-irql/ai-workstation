[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateRange(100, 1000000)][int]$PilotArticles = 10000,
    [ValidateRange(1, 512)][int]$BatchSize = 128,
    [ValidateRange(1, 8)][int]$EmbeddingWorkers = 2,
    [string]$ModelId,
    [switch]$Force,
    [switch]$Unload
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run the RAG virtual-environment setup first.' }
$env:PYTHONPATH = Join-Path $root 'rag\src'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-pilot-$PilotArticles.sqlite3"
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-pilot-$PilotArticles"
$suite = Join-Path $root 'rag\eval\wikipedia-semantic-challenge-v2.json'
$result = Join-Path $root "results\rag\semantic-pilot-$PilotArticles-v1.json"
$models = Join-Path $root 'config\models.json'
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "Pilot BM25 database does not exist: $database"
}

$commonModelArguments = @('--models', $models)
if ($ModelId) { $commonModelArguments += @('--model-id', $ModelId) }
$buildArguments = @(
    '-m', 'offline_rag.vector_index', 'build',
    '--database', $database,
    '--output', $vectorDirectory,
    '--batch-size', $BatchSize,
    '--embedding-workers', $EmbeddingWorkers,
    '--max-chunks', 1,
    '--max-characters', 4000
) + $commonModelArguments
if ($Force) { $buildArguments += '--overwrite' }

try {
    & $python @buildArguments
    if ($LASTEXITCODE -ne 0) { throw 'Semantic pilot index build failed.' }
    & $python -m offline_rag.vector_index evaluate `
        --database $database `
        --index $vectorDirectory `
        --suite $suite `
        --output $result `
        @commonModelArguments
    if ($LASTEXITCODE -ne 0) { throw 'Semantic pilot evaluation failed.' }
    Write-Output "Semantic pilot index: $vectorDirectory"
    Write-Output "Evaluation evidence: $result"
}
finally {
    if ($Unload) {
        $registry = Get-Content -Raw -LiteralPath $models | ConvertFrom-Json
        $selected = if ($ModelId) {
            $registry.models | Where-Object { $_.id -eq $ModelId -and $_.role -eq 'embedding' } | Select-Object -First 1
        }
        else {
            $registry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
        }
        if ($selected) { ollama stop $selected.ollama_model | Out-Null }
    }
}
