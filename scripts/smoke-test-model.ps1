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
$contextTokens = if ($model.PSObject.Properties['context_tokens']) { [int]$model.context_tokens } else { [int]$registry.defaults.context_tokens }
$maxOutputTokens = if ($model.PSObject.Properties['max_output_tokens']) { [int]$model.max_output_tokens } else { [int]$registry.defaults.max_output_tokens }
$temperature = if ($model.PSObject.Properties['temperature']) { [double]$model.temperature } else { 0.0 }
$topP = if ($model.PSObject.Properties['top_p']) { [double]$model.top_p } else { 0.9 }
$topK = if ($model.PSObject.Properties['top_k']) { [int]$model.top_k } else { 40 }
$thinking = if ($model.PSObject.Properties['thinking']) { [bool]$model.thinking } else { $false }
$body = [ordered]@{
    model = $model.ollama_model
    messages = @(@{ role = 'user'; content = 'Reply with exactly: LOCAL_MODEL_OK' })
    stream = $false
    think = $thinking
    options = @{
        num_ctx = $contextTokens
        num_predict = $maxOutputTokens
        temperature = $temperature
        top_p = $topP
        top_k = $topK
        seed = 42
    }
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
    context_requested = $contextTokens
    max_output_requested = $maxOutputTokens
    thinking_requested = $thinking
    sampling = [ordered]@{
        temperature = $temperature
        top_p = $topP
        top_k = $topK
    }
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
