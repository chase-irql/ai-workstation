[CmdletBinding()]
param([string]$DatasetId)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$datasets = @($registry.datasets | Where-Object {
    $_.paths.PSObject.Properties['semantic_index'] -and (-not $DatasetId -or $_.dataset_id -eq $DatasetId)
})
if ($DatasetId -and $datasets.Count -ne 1) { throw "Semantic dataset '$DatasetId' was not found." }

$now = Get-Date
$results = foreach ($dataset in $datasets) {
    $directory = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.semantic_index)))
    $manifestPath = Join-Path $directory 'manifest.json'
    $statePath = Join-Path $directory '.chunk-build-state.json'
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $completed = [long]$state.completed_chunks
        $total = [long]$state.source_identity.chunk_count
        $started = [datetime]$state.started_at
        $elapsed = [math]::Max(0.001, ($now - $started.ToLocalTime()).TotalSeconds)
        $rate = $completed / $elapsed
        [pscustomobject]@{
            dataset_id = [string]$dataset.dataset_id
            status = 'building'
            completed_chunks = $completed
            total_chunks = $total
            percent = [math]::Round(100 * $completed / $total, 2)
            chunks_per_second = [math]::Round($rate, 2)
            eta_minutes = if ($rate -gt 0) { [math]::Round(($total - $completed) / $rate / 60, 1) } else { $null }
            generation = [string]$state.generation
            checkpointed_at = $state.checkpointed_at
            directory = $directory
        }
    }
    elseif (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        [pscustomobject]@{
            dataset_id = [string]$dataset.dataset_id
            status = 'published'
            completed_chunks = [long]$manifest.chunk_count
            total_chunks = [long]$manifest.chunk_count
            percent = 100.0
            chunks_per_second = if ($manifest.elapsed_seconds) {
                [math]::Round([long]$manifest.chunk_count / [double]$manifest.elapsed_seconds, 2)
            } else { $null }
            eta_minutes = 0.0
            generation = [string]$manifest.generation
            checkpointed_at = $manifest.built_at
            directory = $directory
        }
    }
    else {
        [pscustomobject]@{
            dataset_id = [string]$dataset.dataset_id
            status = 'not_started'
            completed_chunks = 0
            total_chunks = $null
            percent = 0.0
            chunks_per_second = $null
            eta_minutes = $null
            generation = $null
            checkpointed_at = $null
            directory = $directory
        }
    }
}
$results | ConvertTo-Json -Depth 5
