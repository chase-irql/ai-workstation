[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$runtime = Join-Path $root 'runtime\wikipedia-semantic-full'
$pidPath = Join-Path $runtime 'build.pid'
$sessionPath = Join-Path $runtime 'session.json'
$checkpointPath = Join-Path $vectorDirectory '.build-state.json'
$manifestPath = Join-Path $vectorDirectory 'manifest.json'
$stdoutPath = Join-Path $runtime 'build.stdout.log'
$stderrPath = Join-Path $runtime 'build.stderr.log'

$process = $null
if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.CommandLine -match 'offline_rag\.vector_index build') { $process = $candidate }
}
$checkpoint = if (Test-Path -LiteralPath $checkpointPath -PathType Leaf) {
    Get-Content -Raw -LiteralPath $checkpointPath | ConvertFrom-Json
} else { $null }
$manifest = if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
} else { $null }
$session = if (Test-Path -LiteralPath $sessionPath -PathType Leaf) {
    Get-Content -Raw -LiteralPath $sessionPath | ConvertFrom-Json
} else { $null }

$completed = if ($checkpoint) { [long]$checkpoint.completed_documents } elseif ($manifest) { [long]$manifest.document_count } else { 0 }
$total = if ($checkpoint) { [long]$checkpoint.source_identity.searchable_document_count } elseif ($manifest) { [long]$manifest.document_count } else { 0 }
$rate = 0.0
$etaHours = $null
if ($process -and $session) {
    $elapsed = ([DateTimeOffset]::Now - [DateTimeOffset]::Parse($session.started_at)).TotalSeconds
    $delta = $completed - [long]$session.initial_completed_documents
    if ($elapsed -gt 0 -and $delta -gt 0) {
        $rate = $delta / $elapsed
        $etaHours = ($total - $completed) / $rate / 3600.0
    }
}
$rawBytes = if ($checkpoint) { [long]$checkpoint.raw_vector_bytes } else { 0 }
$disk = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).TrimEnd(':\'))

[pscustomobject]@{
    Status = if ($process) { 'Running' } elseif ($manifest -and -not $checkpoint) { 'Complete' } elseif ($checkpoint) { 'Interrupted - resumable' } else { 'Not started' }
    ProcessId = if ($process) { $process.ProcessId } else { $null }
    CompletedDocuments = $completed
    TotalDocuments = $total
    Percent = if ($total) { [math]::Round($completed / $total * 100, 3) } else { 0 }
    DocumentsPerSecond = [math]::Round($rate, 2)
    EstimatedHoursRemaining = if ($null -ne $etaHours) { [math]::Round($etaHours, 2) } else { $null }
    CheckpointGiB = [math]::Round($rawBytes / 1GB, 3)
    FreeGiB = [math]::Round($disk.Free / 1GB, 1)
    LastCheckpoint = if ($checkpoint) { $checkpoint.checkpointed_at } else { $null }
    Generation = if ($checkpoint) { $checkpoint.generation } elseif ($manifest) { $manifest.generation } else { $null }
} | Format-List

if (-not $process -and $checkpoint) {
    Write-Output 'Resume command:'
    Write-Output '.\scripts\run-wikipedia-semantic-full.ps1 -Resume -Background'
}
if (-not $process -and (Test-Path -LiteralPath $stderrPath -PathType Leaf)) {
    $errors = Get-Content -LiteralPath $stderrPath -Tail 10
    if ($errors) {
        Write-Output 'Latest stderr:'
        $errors
    }
}
if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
    Write-Output 'Latest progress:'
    Get-Content -LiteralPath $stdoutPath -Tail 3
}
