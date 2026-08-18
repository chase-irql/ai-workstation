[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateRange(1, 512)][int]$BatchSize = 128,
    [ValidateRange(1, 8)][int]$EmbeddingWorkers = 2,
    [ValidateRange(128, 1000000)][int]$CheckpointInterval = 4096,
    [string]$ModelId,
    [ValidatePattern('^\d{8}$')][string]$ReuseFromDumpDate,
    [switch]$SkipReuseChecksums,
    [switch]$Force,
    [switch]$Resume,
    [switch]$Restart,
    [switch]$Background,
    [switch]$Unload
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$reuseDirectory = if ($ReuseFromDumpDate) {
    Join-Path $root "indexes\wikipedia\enwiki-$ReuseFromDumpDate-semantic-full"
} else { $null }
$runtime = Join-Path $root 'runtime\wikipedia-semantic-full'
$pidPath = Join-Path $runtime 'build.pid'
$sessionPath = Join-Path $runtime 'session.json'
$stdoutPath = Join-Path $runtime 'build.stdout.log'
$stderrPath = Join-Path $runtime 'build.stderr.log'
$monitorPidPath = Join-Path $runtime 'monitor.pid'
$monitorStdoutPath = Join-Path $runtime 'monitor.stdout.log'
$monitorStderrPath = Join-Path $runtime 'monitor.stderr.log'
$models = Join-Path $root 'config\models.json'
$env:PYTHONPATH = Join-Path $root 'rag\src'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python virtual environment not found: $python" }
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw "Full Wikipedia database not found: $database" }
if ($ReuseFromDumpDate -and $ReuseFromDumpDate -eq $DumpDate) {
    throw '-ReuseFromDumpDate must identify the previous dump, not the destination dump.'
}
if ($SkipReuseChecksums -and -not $ReuseFromDumpDate) {
    throw '-SkipReuseChecksums requires -ReuseFromDumpDate.'
}
if ($reuseDirectory -and -not (Test-Path -LiteralPath (Join-Path $reuseDirectory 'manifest.json') -PathType Leaf)) {
    throw "Previous semantic generation not found: $reuseDirectory"
}
if ($Resume -and $Restart) { throw '-Resume and -Restart are mutually exclusive.' }
if ($Background -and $Unload) { throw '-Unload is available only for foreground builds; background models expire through Ollama keep-alive.' }

$arguments = @(
    '-m', 'offline_rag.vector_index', 'build',
    '--database', $database,
    '--output', $vectorDirectory,
    '--models', $models,
    '--batch-size', $BatchSize,
    '--embedding-workers', $EmbeddingWorkers,
    '--checkpoint-interval', $CheckpointInterval,
    '--max-chunks', 1,
    '--max-characters', 4000
)
if ($ModelId) { $arguments += @('--model-id', $ModelId) }
if ($reuseDirectory) { $arguments += @('--reuse-from', $reuseDirectory) }
if ($SkipReuseChecksums) { $arguments += '--skip-reuse-checksums' }
if ($Force) { $arguments += '--overwrite' }
if ($Resume) { $arguments += '--resume' }
if ($Restart) { $arguments += '--restart' }

if (-not $Background) {
    try {
        & $python @arguments
        exit $LASTEXITCODE
    }
    finally {
        if ($Unload) {
            $registry = Get-Content -Raw -LiteralPath $models | ConvertFrom-Json
            $selected = if ($ModelId) {
                $registry.models | Where-Object { $_.id -eq $ModelId -and $_.role -eq 'embedding' } | Select-Object -First 1
            }
            else {
                $registry.models | Where-Object role -eq 'embedding' | Sort-Object priority, id | Select-Object -First 1
            }
            if ($selected) { ollama stop $selected.ollama_model | Out-Null }
        }
    }
}

New-Item -ItemType Directory -Force -Path $runtime, $vectorDirectory | Out-Null
if (Test-Path -LiteralPath $pidPath) {
    $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine -match 'offline_rag\.vector_index build') {
        throw "Full semantic build is already running as PID $recordedPid."
    }
    Remove-Item -LiteralPath $pidPath -Force
}

$initialCompleted = 0
$checkpointPath = Join-Path $vectorDirectory '.build-state.json'
if (Test-Path -LiteralPath $checkpointPath -PathType Leaf) {
    $checkpoint = Get-Content -Raw -LiteralPath $checkpointPath | ConvertFrom-Json
    $initialCompleted = [long]$checkpoint.completed_documents
}
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
Set-Content -LiteralPath "$pidPath.tmp" -Value $process.Id -Encoding ascii
Move-Item -LiteralPath "$pidPath.tmp" -Destination $pidPath -Force
[ordered]@{
    pid = $process.Id
    started_at = [DateTimeOffset]::Now.ToString('o')
    initial_completed_documents = $initialCompleted
    batch_size = $BatchSize
    embedding_workers = $EmbeddingWorkers
    checkpoint_interval = $CheckpointInterval
    resume = [bool]$Resume
    reuse_from_dump_date = $ReuseFromDumpDate
} | ConvertTo-Json | Set-Content -LiteralPath "$sessionPath.tmp" -Encoding utf8
Move-Item -LiteralPath "$sessionPath.tmp" -Destination $sessionPath -Force

$monitorScript = Join-Path $PSScriptRoot 'monitor-wikipedia-semantic-full.ps1'
$monitorArguments = @('-NoProfile', '-File', $monitorScript, '-BuildPid', "$($process.Id)", '-DumpDate', $DumpDate)
$monitor = Start-Process -FilePath (Join-Path $PSHOME 'pwsh.exe') -ArgumentList $monitorArguments -WorkingDirectory $root `
    -RedirectStandardOutput $monitorStdoutPath -RedirectStandardError $monitorStderrPath -WindowStyle Hidden -PassThru
Set-Content -LiteralPath "$monitorPidPath.tmp" -Value $monitor.Id -Encoding ascii
Move-Item -LiteralPath "$monitorPidPath.tmp" -Destination $monitorPidPath -Force

Start-Sleep -Milliseconds 500
if ($process.HasExited) {
    $details = Get-Content -LiteralPath $stderrPath -Tail 30 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    throw "Semantic build exited during startup. $details"
}
[ordered]@{
    status = 'running'
    pid = $process.Id
    monitor_pid = $monitor.Id
    database = $database
    vector_directory = $vectorDirectory
    status_command = '.\scripts\get-wikipedia-semantic-status.ps1'
} | ConvertTo-Json
