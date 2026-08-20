[CmdletBinding()]
param(
    [string]$ModelId
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
$providerConfig = Join-Path $root 'config\harnesses\opencode.json'
if (-not (Test-Path -LiteralPath $providerConfig -PathType Leaf)) {
    throw "OpenCode provider configuration not found: $providerConfig"
}

$savedEnvironment = @{}
foreach ($name in @(
    'OPENCODE_CONFIG',
    'OPENCODE_CONFIG_DIR',
    'XDG_CONFIG_HOME',
    'OPENCODE_DISABLE_AUTOUPDATE',
    'OPENCODE_AUTO_SHARE',
    'OPENCODE_DISABLE_CLAUDE_CODE'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:OPENCODE_CONFIG = $providerConfig
    $env:OPENCODE_CONFIG_DIR = Join-Path $root 'runtime\opencode-rag-config'
    $env:XDG_CONFIG_HOME = Join-Path $root 'runtime\xdg-rag-config'
    $env:OPENCODE_DISABLE_AUTOUPDATE = 'true'
    $env:OPENCODE_AUTO_SHARE = 'false'
    $env:OPENCODE_DISABLE_CLAUDE_CODE = '1'
    New-Item -ItemType Directory -Force -Path $env:OPENCODE_CONFIG_DIR, $env:XDG_CONFIG_HOME | Out-Null

    Push-Location $root
    try {
        & opencode . --pure -m "ollama/$($model.ollama_model)"
        $openCodeExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    exit $openCodeExitCode
}
finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
