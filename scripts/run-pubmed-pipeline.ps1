[CmdletBinding()]
param(
    [ValidateRange(128, 20000)][int]$MaxChars = 3200,
    [ValidateRange(0, 20000)][int]$MinChars = 200,
    [ValidateRange(1, 19)][int]$ZstdLevel = 6,
    [ValidateRange(1, 32)][int]$Workers = 8,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$dataset = @($registry.datasets | Where-Object dataset_id -eq 'pubmed-baseline-2026')
if ($dataset.Count -ne 1) { throw 'PubMed registry entry is missing or duplicated.' }
$dataset = $dataset[0]
$raw = [IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.raw)))
$processed = [IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
$database = [IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
$manifest = Join-Path $raw 'acquisition-manifest.json'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw 'PubMed acquisition is not complete and validated; resume acquire-dataset.ps1 first.'
}
$runtime = Join-Path $root 'runtime\pubmed-baseline-2026'
New-Item -ItemType Directory -Force -Path $runtime, (Split-Path -Parent $processed), (Split-Path -Parent $database) | Out-Null
$env:PYTHONPATH = Join-Path $root 'rag\src'

function Send-PubMedAlert([string]$Message) {
    $webhookFile = Join-Path $root 'WEBHOOK.txt'
    if (-not (Test-Path -LiteralPath $webhookFile -PathType Leaf)) { return }
    $webhookText = Get-Content -LiteralPath $webhookFile -Raw
    $match = [regex]::Match($webhookText, 'https://discord(?:app)?\.com/api/webhooks/[^\s]+')
    if (-not $match.Success) { return }
    $payload = @{ content = "<@1495692868784885830> $Message" } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Method Post -Uri $match.Value -ContentType 'application/json' -Body $payload | Out-Null
    } catch {
        Add-Content -LiteralPath (Join-Path $runtime 'alerts.log') -Value "$(Get-Date -Format o) Discord alert failed: $($_.Exception.Message)"
    }
}

$arguments = @(
    '-m', 'offline_rag.pubmed',
    '--source-root', $raw,
    '--output', $processed,
    '--corpus', ([string]$dataset.dataset_id),
    '--source-version', ([string]$dataset.release),
    '--license', ([string]$dataset.license),
    '--max-chars', $MaxChars,
    '--min-chars', $MinChars,
    '--zstd-level', $ZstdLevel
    '--workers', $Workers
)
if ($Force) { $arguments += '--force' }
$lastAlertedPart = 0
try {
    $processedManifestPath = Join-Path $processed 'corpus-manifest.json'
    $processedReady = $false
    if ((-not $Force) -and (Test-Path -LiteralPath $processedManifestPath -PathType Leaf)) {
        $processedManifest = Get-Content -LiteralPath $processedManifestPath -Raw | ConvertFrom-Json
        $processedReady = (
            [bool]$processedManifest.completed -and
            [string]$processedManifest.corpus -eq [string]$dataset.dataset_id -and
            [int]$processedManifest.parts.Count -eq 1334
        )
    }
    if ($processedReady) {
        Write-Output "Reusing validated processed PubMed corpus: $processed"
    } else {
        Send-PubMedAlert 'PubMed streaming import started; the first production shard pilot passed.'
        & $python @arguments 2>&1 | ForEach-Object {
            $line = [string]$_
            Add-Content -LiteralPath (Join-Path $runtime 'import.log') -Value $line
            Write-Output $line
            if ($line.StartsWith('PUBMED_PROGRESS ')) {
                try {
                    $state = $line.Substring('PUBMED_PROGRESS '.Length) | ConvertFrom-Json
                    $completed = [int]$state.completed_files
                    if ($completed -eq [int]$state.total_files -or $completed -ge ($lastAlertedPart + 100)) {
                        $lastAlertedPart = $completed
                        $percent = [math]::Round(100.0 * $completed / [int]$state.total_files, 1)
                        Send-PubMedAlert "PubMed parsing: $completed/$($state.total_files) source files ($percent%), $($state.documents) documents and $($state.chunks) chunks."
                    }
                } catch {
                    Add-Content -LiteralPath (Join-Path $runtime 'alerts.log') -Value "$(Get-Date -Format o) Could not parse progress line: $line"
                }
            }
        }
        if ($LASTEXITCODE -ne 0) { throw 'PubMed import failed or stopped before completion.' }
    }
    Send-PubMedAlert 'PubMed parsing completed and validated; BM25 index construction is starting.'
    $indexArguments = @('-m', 'offline_rag.bm25', 'build', '--input', $processed, '--database', $database)
    if ($Force) { $indexArguments += '--overwrite' }
    $lastIndexAlert = @{}
    & $python @indexArguments 2>&1 | ForEach-Object {
        $line = [string]$_
        Add-Content -LiteralPath (Join-Path $runtime 'index.log') -Value $line
        Write-Output $line
        if ($line.StartsWith('BM25_PROGRESS ')) {
            try {
                $state = $line.Substring('BM25_PROGRESS '.Length) | ConvertFrom-Json
                $phase = [string]$state.phase
                $completed = [int64]$state.completed
                $previous = if ($lastIndexAlert.ContainsKey($phase)) { [int64]$lastIndexAlert[$phase] } else { -10000000 }
                if ($completed -eq 0 -or $completed -ge ($previous + 10000000)) {
                    $lastIndexAlert[$phase] = $completed
                    Send-PubMedAlert "PubMed BM25 phase '$phase': $completed rows completed."
                }
            } catch {
                Add-Content -LiteralPath (Join-Path $runtime 'alerts.log') -Value "$(Get-Date -Format o) Could not parse BM25 progress line: $line"
            }
        }
    }
    if ($LASTEXITCODE -ne 0) { throw 'PubMed BM25 indexing failed.' }
    Send-PubMedAlert 'PubMed BM25 index construction and structural validation completed. Return to the PC for retrieval evaluation and MCP activation.'
    Write-Output "Processed corpus: $processed"
    Write-Output "BM25 database: $database"
} catch {
    Send-PubMedAlert "PubMed pipeline stopped: $($_.Exception.Message) Return to the PC for inspection."
    throw
}
