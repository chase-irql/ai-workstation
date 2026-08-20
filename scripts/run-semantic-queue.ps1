[CmdletBinding()]
param(
    [string[]]$DatasetIds = @(
        'electronics-stackexchange',
        'unix-stackexchange',
        'serverfault-stackexchange'
    ),
    [ValidateRange(50, 1000)][int]$ReserveGiB = 200,
    [ValidateRange(1, 8)][int]$EmbeddingWorkers = 2,
    [ValidateRange(1, 1024)][int]$BatchSize = 128,
    [ValidateRange(128, 100000)][int]$CheckpointInterval = 4096,
    [string]$StatusPath = 'runtime\semantic-queue-status.json'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$statusFile = [System.IO.Path]::GetFullPath((Join-Path $root $StatusPath))
$statusDirectory = Split-Path -Parent $statusFile
New-Item -ItemType Directory -Force -Path $statusDirectory | Out-Null
$lockFile = Join-Path $statusDirectory 'semantic-queue.lock'
$lockStream = $null

function Write-QueueStatus {
    param(
        [Parameter(Mandatory)][string]$State,
        [string]$DatasetId,
        [int]$Completed = 0,
        [string]$Message,
        [datetime]$StartedAt
    )
    $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).Substring(0, 1))
    $value = [ordered]@{
        schema_version = 1
        state = $State
        dataset_id = $DatasetId
        completed_datasets = $Completed
        total_datasets = $DatasetIds.Count
        free_bytes = [int64]$drive.Free
        reserve_bytes = [int64]$ReserveGiB * 1GB
        message = $Message
        started_at = if ($StartedAt) { $StartedAt.ToUniversalTime().ToString('o') } else { $null }
        updated_at = [datetime]::UtcNow.ToString('o')
    }
    $temporary = "$statusFile.tmp-$PID"
    $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statusFile -Force
}

try {
    $lockStream = [System.IO.File]::Open(
        $lockFile,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $startedAt = [datetime]::UtcNow
    Write-QueueStatus -State 'running' -Completed 0 -Message 'Queue initialized.' -StartedAt $startedAt

    for ($index = 0; $index -lt $DatasetIds.Count; $index++) {
        $datasetId = $DatasetIds[$index]
        $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).Substring(0, 1))
        if ([int64]$drive.Free -lt ([int64]$ReserveGiB * 1GB)) {
            throw "Free space fell below the ${ReserveGiB} GiB reserve before '$datasetId'."
        }
        Write-QueueStatus -State 'embedding' -DatasetId $datasetId -Completed $index -Message 'Building and verifying semantic generation.' -StartedAt $startedAt
        & (Join-Path $PSScriptRoot 'run-corpus-semantic.ps1') `
            -DatasetId $datasetId `
            -EmbeddingWorkers $EmbeddingWorkers `
            -BatchSize $BatchSize `
            -CheckpointInterval $CheckpointInterval `
            -Unload
        if ($LASTEXITCODE -ne 0) { throw "Semantic build failed for '$datasetId'." }

        $suite = Join-Path $root "rag\eval\$datasetId-semantic-v1.json"
        if (-not (Test-Path -LiteralPath $suite -PathType Leaf)) {
            throw "Semantic evaluation suite does not exist: $suite"
        }
        Write-QueueStatus -State 'evaluating' -DatasetId $datasetId -Completed $index -Message 'Comparing BM25, semantic, and hybrid retrieval.' -StartedAt $startedAt
        & (Join-Path $PSScriptRoot 'evaluate-corpus-semantic.ps1') `
            -DatasetId $datasetId `
            -Suite $suite `
            -Mode all `
            -Unload
        if ($LASTEXITCODE -ne 0) { throw "Semantic evaluation failed for '$datasetId'." }

        Write-QueueStatus -State 'running' -DatasetId $datasetId -Completed ($index + 1) -Message 'Corpus completed and verified.' -StartedAt $startedAt
    }
    Write-QueueStatus -State 'complete' -Completed $DatasetIds.Count -Message 'All queued corpora completed and verified.' -StartedAt $startedAt
} catch {
    Write-QueueStatus -State 'failed' -DatasetId $datasetId -Completed $index -Message $_.Exception.Message -StartedAt $startedAt
    throw
} finally {
    if ($lockStream) { $lockStream.Dispose() }
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
}
