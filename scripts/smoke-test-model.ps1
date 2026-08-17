[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$ModelId)

. (Join-Path $PSScriptRoot 'common.ps1')
$model = Get-ModelDefinition -ModelId $ModelId
$registry = Get-ModelRegistry
$root = Get-ProjectRoot
$resultDir = Join-Path $root 'results\smoke-tests'
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$show = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/show' -ContentType 'application/json' -Body (@{ model = $model.ollama_model } | ConvertTo-Json) -TimeoutSec 30
$body = [ordered]@{
    model = $model.ollama_model
    messages = @(@{ role = 'user'; content = 'Reply with exactly: LOCAL_MODEL_OK' })
    stream = $false
    options = @{ num_ctx = [int]$registry.defaults.context_tokens; temperature = 0; seed = 42 }
}
$gpuBefore = Get-GpuSnapshot
$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/chat' -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 6) -TimeoutSec 900
$gpuAfter = Get-GpuSnapshot
$running = Get-OllamaRunningModels

$report = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    model_id = $ModelId
    ollama_model = $model.ollama_model
    quantization = $show.details.quantization_level
    capabilities = @($show.capabilities)
    context_requested = [int]$registry.defaults.context_tokens
    response = $response.message.content
    load_duration_ns = $response.load_duration
    prompt_tokens = $response.prompt_eval_count
    prompt_duration_ns = $response.prompt_eval_duration
    output_tokens = $response.eval_count
    output_duration_ns = $response.eval_duration
    gpu_before = $gpuBefore
    gpu_after = $gpuAfter
    ollama_ps = $running
}
$path = Join-Path $resultDir "$stamp-$ModelId.json"
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding UTF8
$report | ConvertTo-Json -Depth 12
if ($response.message.content -notmatch 'LOCAL_MODEL_OK') { exit 1 }

