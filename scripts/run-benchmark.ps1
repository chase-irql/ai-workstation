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
Get-ChildItem -LiteralPath $seed -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $workspace -Recurse -Force
}
& git -C $workspace init --quiet
& git -C $workspace config user.name 'Local AI Benchmark'
& git -C $workspace config user.email 'benchmark@localhost'
& git -C $workspace add --all
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
        Get-Content -Raw -LiteralPath $promptPath | & codex exec --ignore-user-config --ephemeral --oss --local-provider ollama -m $model.ollama_model -s workspace-write -a never --json -C $workspace - 2>&1 | Tee-Object -FilePath $rawLog
        $exitCode = $LASTEXITCODE
    } else {
        $env:OPENCODE_CONFIG = Join-Path $root 'config\harnesses\opencode.json'
        $env:OPENCODE_DISABLE_AUTOUPDATE = 'true'
        $env:OPENCODE_AUTO_SHARE = 'false'
        & opencode run --format json --dir $workspace -m "ollama/$($model.ollama_model)" $task.prompt 2>&1 | Tee-Object -FilePath $rawLog
        $exitCode = $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$finished = Get-Date
$gpuAfter = Get-GpuSnapshot
$verifyLog = Join-Path $runDir 'verification.txt'
Push-Location $workspace
try {
    & $task.verify.command @($task.verify.args) 2>&1 | Tee-Object -FilePath $verifyLog
    $verifyExit = $LASTEXITCODE
    & git status --short | Set-Content -LiteralPath (Join-Path $runDir 'git-status.txt') -Encoding UTF8
    & git diff --stat | Set-Content -LiteralPath (Join-Path $runDir 'diff-stat.txt') -Encoding UTF8
    & git diff --binary | Set-Content -LiteralPath (Join-Path $runDir 'changes.patch') -Encoding UTF8
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
    verification_exit_code = $verifyExit
    passed = ($verifyExit -eq 0)
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
