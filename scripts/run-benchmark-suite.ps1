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
    [ValidateRange(1, 20)][int]$Repeats = 1,
    [ValidateRange(60, 7200)][int]$MaxRunSeconds = 420,
    [string]$ResumeSuiteId
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$benchmark = Join-Path $PSScriptRoot 'run-benchmark.ps1'
$runsRoot = Join-Path $root 'results\runs'
$suiteId = if ($ResumeSuiteId) { $ResumeSuiteId } else { "$(Get-Date -Format 'yyyyMMdd-HHmmss')-expanded" }
$suiteRoot = Join-Path $root "results\suites\$suiteId"
New-Item -ItemType Directory -Force -Path $suiteRoot | Out-Null
$shell = (Get-Process -Id $PID).Path
$records = [System.Collections.Generic.List[object]]::new()
$progressPath = Join-Path $suiteRoot 'progress.jsonl'
if ($ResumeSuiteId -and (Test-Path -LiteralPath $progressPath)) {
    foreach ($line in Get-Content -LiteralPath $progressPath) {
        if ($line.Trim()) { $records.Add(($line | ConvertFrom-Json)) }
    }
}
$ordinal = 0
$total = $Repeats * $ModelIds.Count * $TaskIds.Count * $Harnesses.Count

function Stop-BenchmarkProcessTree {
    param([Parameter(Mandatory = $true)][int]$RootProcessId)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-BenchmarkProcessTree -RootProcessId $child.ProcessId
    }
    if (Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $RootProcessId -Force
    }
}

for ($repeat = 1; $repeat -le $Repeats; $repeat++) {
    foreach ($modelId in $ModelIds) {
        foreach ($taskId in $TaskIds) {
            foreach ($harness in $Harnesses) {
                $ordinal++
                $label = "r$repeat-$modelId-$taskId-$harness"
                $alreadyRecorded = @($records | Where-Object {
                    $_.repeat -eq $repeat -and $_.model_id -eq $modelId -and
                    $_.task_id -eq $taskId -and $_.harness -eq $harness
                })
                if ($alreadyRecorded.Count) {
                    Write-Output "SKIP  $ordinal/$total $label already recorded"
                    continue
                }
                $stdout = Join-Path $suiteRoot "$label.stdout.log"
                $stderr = Join-Path $suiteRoot "$label.stderr.log"
                $known = @{}
                Get-ChildItem -LiteralPath $runsRoot -Directory | ForEach-Object { $known[$_.Name] = $true }
                $started = Get-Date
                Write-Output "START $ordinal/$total $label $($started.ToString('s'))"

                $arguments = @(
                    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $benchmark,
                    '-Harness', $harness, '-ModelId', $modelId, '-TaskId', $taskId
                )
                $process = Start-Process -FilePath $shell -ArgumentList $arguments -PassThru `
                    -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
                $timedOut = -not $process.WaitForExit($MaxRunSeconds * 1000)
                if ($timedOut) {
                    Stop-BenchmarkProcessTree -RootProcessId $process.Id
                    $processExit = 124
                } else {
                    $processExit = $process.ExitCode
                }

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
                    timed_out = $timedOut
                    run_id = if ($metadata) { $metadata.run_id } else { $null }
                    passed = if ($timedOut) { $false } elseif ($metadata) { $metadata.passed } else { $false }
                    wall_seconds = if ($metadata) { $metadata.wall_seconds } else { [math]::Round(((Get-Date) - $started).TotalSeconds, 3) }
                    tool_calls = if ($metadata) { $metadata.tool_calls_observed } else { $null }
                    failed_tool_calls = if ($metadata) { $metadata.failed_tool_calls_observed } else { $null }
                    input_tokens = if ($metadata) { $metadata.input_tokens_observed } else { $null }
                    output_tokens = if ($metadata) { $metadata.output_tokens_observed } else { $null }
                    files_changed = if ($metadata) { $metadata.files_changed } else { $null }
                }
                $records.Add([pscustomobject]$record)
                $record | ConvertTo-Json -Compress | Add-Content -LiteralPath $progressPath -Encoding UTF8
                Write-Output "DONE  $ordinal/$total $label pass=$($record.passed) timeout=$timedOut seconds=$($record.wall_seconds)"
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
