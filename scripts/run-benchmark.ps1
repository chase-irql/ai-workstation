[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('codex','opencode')][string]$Harness,
    [Parameter(Mandatory = $true)][string]$ModelId,
    [Parameter(Mandatory = $true)][string]$TaskId
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$model = Get-ModelDefinition -ModelId $ModelId
$taskPath = Join-Path $root "benchmarks\tasks\$TaskId.json"
if (-not (Test-Path -LiteralPath $taskPath)) { throw "Unknown task '$TaskId'." }
$task = Get-Content -Raw -LiteralPath $taskPath | ConvertFrom-Json

$seed = [System.IO.Path]::GetFullPath((Join-Path $root $task.seed_repository))
if (-not (Test-Path -LiteralPath $seed)) { throw "Seed repository does not exist: $seed" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runId = "$stamp-$TaskId-$Harness-$ModelId"
$runDir = Join-Path $root "results\runs\$runId"
$workspace = Join-Path $runDir 'workspace'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
Get-ChildItem -LiteralPath $seed -Recurse -File -Force |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    ForEach-Object {
        $relative = $_.FullName.Substring($seed.Length).TrimStart('\','/')
        $destination = Join-Path $workspace $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}
& git -C $workspace init --quiet
& git -C $workspace config user.name 'Local AI Benchmark'
& git -C $workspace config user.email 'benchmark@localhost'
& git -C $workspace config core.autocrlf false
& git -C $workspace add --all
$env:GIT_AUTHOR_DATE = '2000-01-01T00:00:00Z'
$env:GIT_COMMITTER_DATE = '2000-01-01T00:00:00Z'
& git -C $workspace commit --quiet -m 'benchmark seed'
if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize benchmark workspace.' }

$promptPath = Join-Path $runDir 'prompt.txt'
$task.prompt | Set-Content -LiteralPath $promptPath -Encoding UTF8
$rawLog = Join-Path $runDir 'harness.jsonl'
$started = Get-Date
$gpuBefore = Get-GpuSnapshot
$exitCode = -1

Push-Location $workspace
try {
    if ($Harness -eq 'codex') {
        $codexHome = Join-Path $root 'runtime\codex-home'
        New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
        Copy-Item -LiteralPath (Join-Path $root 'config\harnesses\codex-home\config.toml') -Destination (Join-Path $codexHome 'config.toml') -Force
        $env:CODEX_HOME = $codexHome
        Get-Content -Raw -LiteralPath $promptPath | & codex exec --ephemeral --approve-for-me --ignore-rules -m $model.ollama_model -c 'web_search="disabled"' --json -C $workspace - 2>&1 | Tee-Object -FilePath $rawLog
        $exitCode = $LASTEXITCODE
    } else {
        $env:OPENCODE_CONFIG = Join-Path $root 'config\harnesses\opencode.json'
        $env:OPENCODE_CONFIG_DIR = Join-Path $root 'runtime\opencode-config'
        $env:XDG_CONFIG_HOME = Join-Path $root 'runtime\xdg-config'
        New-Item -ItemType Directory -Force -Path $env:OPENCODE_CONFIG_DIR | Out-Null
        New-Item -ItemType Directory -Force -Path $env:XDG_CONFIG_HOME | Out-Null
        $env:OPENCODE_DISABLE_AUTOUPDATE = 'true'
        $env:OPENCODE_AUTO_SHARE = 'false'
        $env:OPENCODE_DISABLE_CLAUDE_CODE = '1'
        & opencode run --pure --format json --dir $workspace -m "ollama/$($model.ollama_model)" $task.prompt 2>&1 | Tee-Object -FilePath $rawLog
        $exitCode = $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$finished = Get-Date
$gpuAfter = Get-GpuSnapshot
$events = @()
if (Test-Path -LiteralPath $rawLog) {
    foreach ($line in Get-Content -LiteralPath $rawLog) {
        if ($line.TrimStart().StartsWith('{')) {
            try { $events += ($line | ConvertFrom-Json) } catch { }
        }
    }
}
$toolCalls = 0
$failedToolCalls = 0
$inputTokens = 0L
$outputTokens = 0L
foreach ($event in $events) {
    if ($Harness -eq 'codex') {
        if ($event.type -eq 'item.completed' -and $event.item.type -eq 'command_execution') {
            $toolCalls++
            if ($event.item.status -notin @('completed','success') -or ($null -ne $event.item.exit_code -and $event.item.exit_code -ne 0)) {
                $failedToolCalls++
            }
        }
        if ($event.type -eq 'turn.completed' -and $event.usage) {
            $inputTokens += [long]$event.usage.input_tokens
            $outputTokens += [long]$event.usage.output_tokens
        }
    } else {
        if ($event.type -eq 'tool_use') {
            $toolCalls++
            if ($event.part.state.status -ne 'completed') { $failedToolCalls++ }
        }
        if ($event.type -eq 'step_finish' -and $event.part.tokens) {
            $inputTokens += [long]$event.part.tokens.input
            $outputTokens += [long]$event.part.tokens.output
        }
    }
}
$verifyLog = Join-Path $runDir 'verification.txt'
Push-Location $workspace
try {
    & $task.verify.command @($task.verify.args) 2>&1 | Tee-Object -FilePath $verifyLog
    $verifyExit = $LASTEXITCODE
    & git status --short | Set-Content -LiteralPath (Join-Path $runDir 'git-status.txt') -Encoding UTF8
    & git diff --stat | Set-Content -LiteralPath (Join-Path $runDir 'diff-stat.txt') -Encoding UTF8
    & git diff --binary | Set-Content -LiteralPath (Join-Path $runDir 'changes.patch') -Encoding UTF8
    $numstat = @(& git diff --numstat)
} finally {
    Pop-Location
}

$metadata = [ordered]@{
    schema_version = 1
    run_id = $runId
    task_id = $TaskId
    harness = $Harness
    harness_version = Get-CommandVersion $Harness
    model_id = $ModelId
    ollama_model = $model.ollama_model
    started_at = $started.ToString('o')
    finished_at = $finished.ToString('o')
    wall_seconds = [math]::Round(($finished - $started).TotalSeconds, 3)
    harness_exit_code = $exitCode
    tool_calls_observed = $toolCalls
    failed_tool_calls_observed = $failedToolCalls
    input_tokens_observed = $inputTokens
    output_tokens_observed = $outputTokens
    verification_exit_code = $verifyExit
    passed = ($verifyExit -eq 0)
    files_changed = $numstat.Count
    seed_commit = (& git -C $workspace rev-parse HEAD).Trim()
    context_tokens = (Get-ModelRegistry).defaults.context_tokens
    kv_cache = (Get-ModelRegistry).defaults.kv_cache
    gpu_before = $gpuBefore
    gpu_after = $gpuAfter
    ollama_ps = Get-OllamaRunningModels
}
$metadata | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $runDir 'metadata.json') -Encoding UTF8
$metadata | ConvertTo-Json -Depth 12
if ($verifyExit -ne 0) { exit 2 }
