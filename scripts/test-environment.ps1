[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')

$required = @('git','python','node','ollama','codex','opencode','nvidia-smi')
$commands = foreach ($name in $required) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    [ordered]@{
        name = $name
        found = [bool]$command
        path = if ($command) { $command.Source } else { $null }
        version = if ($command) { Get-CommandVersion $name } else { $null }
    }
}

$settings = [ordered]@{}
foreach ($name in @('OLLAMA_MODELS','OLLAMA_CONTEXT_LENGTH','OLLAMA_FLASH_ATTENTION','OLLAMA_KV_CACHE_TYPE','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS')) {
    $settings[$name] = [Environment]::GetEnvironmentVariable($name, 'User')
}

$ollamaReady = $false
$tags = $null
try {
    $tags = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
    $ollamaReady = $true
} catch { }

$report = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    commands = $commands
    gpu = Get-GpuSnapshot
    ollama_ready = $ollamaReady
    ollama_settings = $settings
    installed_models = if ($tags) { @($tags.models | ForEach-Object { $_.name }) } else { @() }
}

$report | ConvertTo-Json -Depth 8
if (@($commands | Where-Object { -not $_.found }).Count -gt 0 -or -not $ollamaReady) { exit 1 }

