[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateSet('codex', 'opencode', 'all')][string]$Harness = 'all',
    [string]$ListenAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [ValidateRange(0, 4096)][int]$QueryCacheSize = 256,
    [string]$ModelId,
    [bool]$UnloadAfterSmoke = $true
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$runtime = Join-Path $root 'runtime\wikipedia-semantic-full'
$statusPath = Join-Path $runtime 'verification-status.json'
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$manifestPath = Join-Path $vectorDirectory 'manifest.json'
$models = Join-Path $root 'config\models.json'

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    throw 'Semantic verification has not produced a status file.'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Published semantic generation not found: $vectorDirectory"
}
$verification = Get-Content -Raw -LiteralPath $statusPath | ConvertFrom-Json
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($verification.status -ne 'passed') {
    throw "Semantic verification has not passed: $($verification.status)"
}
if ($verification.generation -ne $manifest.generation) {
    throw 'Verification status belongs to a different semantic generation.'
}

& (Join-Path $PSScriptRoot 'stop-wikipedia-service.ps1')
$startArguments = @{
    DumpDate = $DumpDate
    ListenAddress = $ListenAddress
    Port = $Port
    RetrievalMode = 'hybrid'
    QueryCacheSize = $QueryCacheSize
    EnableSemantic = $true
    Background = $true
}
if ($ModelId) { $startArguments.ModelId = $ModelId }
& (Join-Path $PSScriptRoot 'start-wikipedia-service.ps1') @startArguments

$configureArguments = @{
    Harness = $Harness
    DumpDate = $DumpDate
    RetrievalMode = 'hybrid'
    QueryCacheSize = $QueryCacheSize
    EnableSemantic = $true
    Force = $true
}
if ($ModelId) { $configureArguments.ModelId = $ModelId }
& (Join-Path $PSScriptRoot 'configure-wikipedia-mcp.ps1') @configureArguments

$healthUrl = "http://$($ListenAddress):$Port/health"
$searchUrl = "http://$($ListenAddress):$Port/v1/search"
$smoke = Invoke-RestMethod -Uri $searchUrl -Method Post -ContentType 'application/json' -Body (@{
    query = 'Apollo Guidance Computer'
    retrieval_mode = 'hybrid'
    mode = 'and'
    limit = 3
} | ConvertTo-Json) -TimeoutSec 120
if ($smoke.retrieval_mode -ne 'hybrid' -or @($smoke.results).Count -lt 1) {
    throw 'Hybrid service smoke query returned an invalid response.'
}
$health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5

if ($UnloadAfterSmoke) {
    $registry = Get-Content -Raw -LiteralPath $models | ConvertFrom-Json
    $selected = if ($ModelId) {
        $registry.models | Where-Object { $_.id -eq $ModelId -and $_.role -eq 'embedding' } | Select-Object -First 1
    }
    else {
        $registry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
    }
    if ($selected) { ollama stop $selected.ollama_model | Out-Null }
}

[ordered]@{
    status = 'hybrid_enabled'
    generation = $manifest.generation
    url = "http://$($ListenAddress):$Port/"
    default_retrieval = $health.retrieval.default_mode
    available_modes = $health.retrieval.available_modes
    smoke_top_document = $smoke.results[0].document_id
    embedding_model_unloaded = $UnloadAfterSmoke
} | ConvertTo-Json -Depth 6
