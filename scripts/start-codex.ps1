[CmdletBinding()]
param(
    [string]$ModelId,
    [string]$WorkingDirectory = (Get-Location).Path
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-ModelRegistry
if (-not $ModelId) {
    $selected = @($registry.models | Where-Object role -eq 'general-agent' | Sort-Object priority | Select-Object -First 1)
    if ($selected.Count -ne 1) { throw 'No default general-agent model is defined in config/models.json.' }
    $ModelId = $selected[0].id
}
$model = Get-ModelDefinition -ModelId $ModelId

if ($model.role -eq 'embedding') {
    throw "Model '$ModelId' is an embedding model and cannot run as a Codex agent."
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Codex CLI was not found on PATH.'
}
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw "Working directory does not exist: $WorkingDirectory"
}

$catalog = Join-Path $root 'config\harnesses\codex-models.json'
$configTemplate = Join-Path $root 'config\harnesses\codex-home\config.toml'
foreach ($requiredFile in @($catalog, $configTemplate)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required Codex configuration was not found: $requiredFile"
    }
}

try {
    $tags = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
    throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama and try again.'
}
if ($model.ollama_model -notin @($tags.models.name)) {
    throw "Ollama model '$($model.ollama_model)' is not installed. Run .\scripts\pull-model.ps1 -ModelId $ModelId first."
}

$codexHome = Join-Path $root 'runtime\codex-home'
New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
$tomlEscape = {
    param([string]$Value)
    return $Value.Replace('\', '\\').Replace('"', '\"')
}
$renderedConfig = Get-Content -LiteralPath $configTemplate -Raw
$renderedConfig = $renderedConfig.Replace('__MODEL_ID__', (& $tomlEscape ([string]$model.ollama_model)))
$renderedConfig = $renderedConfig.Replace('__MODEL_CATALOG_JSON__', (& $tomlEscape $catalog))
$renderedConfig = $renderedConfig.Replace('__CODEX_HOME__', (& $tomlEscape $codexHome))
$renderedConfig | Set-Content -LiteralPath (Join-Path $codexHome 'config.toml') -Encoding utf8

$savedCodexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
$exitCode = 1
try {
    $env:CODEX_HOME = $codexHome
    Write-Host "Starting Codex with $ModelId ($($model.ollama_model))"
    Write-Host "Workspace: $([System.IO.Path]::GetFullPath($WorkingDirectory))"
    & codex -C $WorkingDirectory -m $model.ollama_model
    $exitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $savedCodexHome, 'Process')
}

exit $exitCode
