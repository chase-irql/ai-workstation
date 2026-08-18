[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$suite = Join-Path $root 'rag\eval\wikipedia-semantic-challenge-v2.json'
$evaluation = Join-Path $root 'results\rag\semantic-full-v1.json'
$runtime = Join-Path $root 'runtime\wikipedia-semantic-full'
$verifyLog = Join-Path $runtime 'verification.log'
$evaluationLog = Join-Path $runtime 'evaluation.log'
$testsLog = Join-Path $runtime 'tests.log'
$statusPath = Join-Path $runtime 'verification-status.json'
$models = Join-Path $root 'config\models.json'
$env:PYTHONPATH = Join-Path $root 'rag\src'
New-Item -ItemType Directory -Force -Path $runtime, (Split-Path -Parent $evaluation) | Out-Null

function Write-VerificationStatus {
    param([hashtable]$Value)
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$statusPath.tmp" -Encoding utf8
    Move-Item -LiteralPath "$statusPath.tmp" -Destination $statusPath -Force
}

try {
    if (Test-Path -LiteralPath (Join-Path $vectorDirectory '.build-state.json')) {
        throw 'Semantic build checkpoint still exists; the generation is not fully published.'
    }
    & $python -m offline_rag.vector_index verify --index $vectorDirectory --database $database `
        2>&1 | Tee-Object -FilePath $verifyLog
    if ($LASTEXITCODE -ne 0) { throw 'Independent vector-index verification failed.' }

    & $python -m offline_rag.vector_index evaluate --database $database --index $vectorDirectory `
        --suite $suite --output $evaluation --models $models --mode all *> $evaluationLog
    if ($LASTEXITCODE -ne 0) { throw 'Full semantic retrieval evaluation failed.' }
    $metrics = Get-Content -Raw -LiteralPath $evaluation | ConvertFrom-Json
    $bm25Success = [double]$metrics.bm25.aggregate.success_at_10
    $semanticSuccess = [double]$metrics.semantic.aggregate.success_at_10
    $hybridSuccess = [double]$metrics.hybrid.aggregate.success_at_10
    if ($semanticSuccess -lt $bm25Success -or $hybridSuccess -lt $bm25Success) {
        throw "Semantic regression: BM25=$bm25Success semantic=$semanticSuccess hybrid=$hybridSuccess"
    }

    & $python -m unittest discover -s rag\tests -v *> $testsLog
    if ($LASTEXITCODE -ne 0) { throw 'Post-build automated tests failed.' }
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $vectorDirectory 'manifest.json') | ConvertFrom-Json
    Write-VerificationStatus @{
        status = 'passed'
        verified_at = [DateTimeOffset]::Now.ToString('o')
        generation = $manifest.generation
        documents = $manifest.document_count
        bm25_success_at_10 = $bm25Success
        semantic_success_at_10 = $semanticSuccess
        hybrid_success_at_10 = $hybridSuccess
        evaluation = $evaluation
    }
}
catch {
    Write-VerificationStatus @{
        status = 'failed'
        failed_at = [DateTimeOffset]::Now.ToString('o')
        error = ($_ | Out-String)
    }
    throw
}
finally {
    $registry = Get-Content -Raw -LiteralPath $models | ConvertFrom-Json
    $model = $registry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
    if ($model) { ollama stop $model.ollama_model | Out-Null }
}
