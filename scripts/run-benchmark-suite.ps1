[CmdletBinding()]
param(
    [string[]]$TaskIds = @(
        'ledger-refund',
        'config-precedence',
        'backup-exclusions',
        'notification-refactor',
        'stock-report-feature'
    ),
    [string[]]$ModelIds = @('devstral-small-2', 'qwen3-coder-30b', 'glm-4.7-flash'),
    [ValidateSet('codex','opencode')][string[]]$Harnesses = @('codex','opencode'),
    [ValidateRange(1, 20)][int]$Repeats = 1
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$benchmark = Join-Path $PSScriptRoot 'run-benchmark.ps1'
$runsRoot = Join-Path $root 'results\runs'
$suiteId = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-expanded"
$suiteRoot = Join-Path $root "results\suites\$suiteId"
New-Item -ItemType Directory -Force -Path $suiteRoot | Out-Null
$shell = (Get-Process -Id $PID).Path
$records = [System.Collections.Generic.List[object]]::new()
$ordinal = 0
$total = $Repeats * $ModelIds.Count * $TaskIds.Count * $Harnesses.Count

for ($repeat = 1; $repeat -le $Repeats; $repeat++) {
    foreach ($modelId in $ModelIds) {
        foreach ($taskId in $TaskIds) {
            foreach ($harness in $Harnesses) {
                $ordinal++
                $label = "r$repeat-$modelId-$taskId-$harness"
                $stdout = Join-Path $suiteRoot "$label.stdout.log"
                $stderr = Join-Path $suiteRoot "$label.stderr.log"
                $known = @{}
                Get-ChildItem -LiteralPath $runsRoot -Directory | ForEach-Object { $known[$_.Name] = $true }
                $started = Get-Date
                Write-Output "START $ordinal/$total $label $($started.ToString('s'))"

                & $shell -NoProfile -ExecutionPolicy Bypass -File $benchmark `
                    -Harness $harness -ModelId $modelId -TaskId $taskId `
                    1> $stdout 2> $stderr
                $processExit = $LASTEXITCODE

                $created = Get-ChildItem -LiteralPath $runsRoot -Directory |
                    Where-Object { -not $known.ContainsKey($_.Name) } |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -First 1
                $metadata = $null
                if ($created) {
                    $metadataPath = Join-Path $created.FullName 'metadata.json'
                    if (Test-Path -LiteralPath $metadataPath) {
                        $metadata = Get-Content -Raw -LiteralPath $metadataPath | ConvertFrom-Json
                    }
                }

                $record = [ordered]@{
                    repeat = $repeat
                    model_id = $modelId
                    task_id = $taskId
                    harness = $harness
                    process_exit_code = $processExit
                    run_id = if ($metadata) { $metadata.run_id } else { $null }
                    passed = if ($metadata) { $metadata.passed } else { $false }
                    wall_seconds = if ($metadata) { $metadata.wall_seconds } else { $null }
                    tool_calls = if ($metadata) { $metadata.tool_calls_observed } else { $null }
                    failed_tool_calls = if ($metadata) { $metadata.failed_tool_calls_observed } else { $null }
                    input_tokens = if ($metadata) { $metadata.input_tokens_observed } else { $null }
                    output_tokens = if ($metadata) { $metadata.output_tokens_observed } else { $null }
                    files_changed = if ($metadata) { $metadata.files_changed } else { $null }
                }
                $records.Add([pscustomobject]$record)
                $record | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $suiteRoot 'progress.jsonl') -Encoding UTF8
                Write-Output "DONE  $ordinal/$total $label pass=$($record.passed) seconds=$($record.wall_seconds)"
            }
        }
    }
}

$summary = [ordered]@{
    schema_version = 1
    suite_id = $suiteId
    finished_at = (Get-Date).ToString('o')
    repeats = $Repeats
    tasks = $TaskIds
    models = $ModelIds
    harnesses = $Harnesses
    records = $records
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $suiteRoot 'summary.json') -Encoding UTF8
$records | Export-Csv -LiteralPath (Join-Path $suiteRoot 'summary.csv') -NoTypeInformation -Encoding UTF8
Write-Output "SUITE $suiteId complete: $(@($records | Where-Object passed).Count)/$total passed"
