[CmdletBinding()]
param(
    [string[]]$DatasetIds,
    [string]$DatasetList,
    [ValidateRange(50, 1000)][int]$ReserveGiB = 200,
    [switch]$Force,
    [string]$StatusPath = 'runtime\documentation-expansion-status.json'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
if ($DatasetList) { $DatasetIds = @($DatasetList.Split(',') | Where-Object { $_ }) }
if (-not $DatasetIds -or $DatasetIds.Count -eq 0) { throw 'Provide -DatasetIds or a comma-separated -DatasetList.' }
$registryPath = Join-Path $root 'config\datasets.json'
$statusFile = [System.IO.Path]::GetFullPath((Join-Path $root $StatusPath))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $statusFile) | Out-Null

function Write-ExpansionStatus {
    param([string]$State, [string]$DatasetId, [int]$Completed, [string]$Message)
    $driveName = [System.IO.Path]::GetPathRoot($root).Substring(0, 1)
    $drive = Get-PSDrive -Name $driveName
    $value = [ordered]@{
        schema_version = 1
        state = $State
        dataset_id = $DatasetId
        completed_datasets = $Completed
        total_datasets = $DatasetIds.Count
        free_bytes = [int64]$drive.Free
        reserve_bytes = [int64]$ReserveGiB * 1GB
        message = $Message
        updated_at = [datetime]::UtcNow.ToString('o')
    }
    $temporary = "$statusFile.tmp-$PID"
    $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statusFile -Force
}

try {
    for ($index = 0; $index -lt $DatasetIds.Count; $index++) {
        $datasetId = $DatasetIds[$index]
        $registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
        $matches = @($registry.datasets | Where-Object dataset_id -eq $datasetId)
        if ($matches.Count -ne 1) { throw "Dataset '$datasetId' is missing or duplicated." }
        $dataset = $matches[0]
        $driveName = [System.IO.Path]::GetPathRoot($root).Substring(0, 1)
        if ([int64](Get-PSDrive -Name $driveName).Free -lt ([int64]$ReserveGiB * 1GB)) {
            throw "Free space fell below the ${ReserveGiB} GiB reserve before '$datasetId'."
        }

        $raw = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.raw)))
        $processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.processed)))
        $database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
        $acquisitionManifest = Join-Path $raw 'acquisition-manifest.json'
        $siteManifest = Join-Path $raw 'site-acquisition-manifest.json'
        if (
            -not (Test-Path -LiteralPath $acquisitionManifest -PathType Leaf) -and
            -not (Test-Path -LiteralPath $siteManifest -PathType Leaf)
        ) {
            Write-ExpansionStatus -State 'acquiring' -DatasetId $datasetId -Completed $index -Message 'Downloading and validating source archive.'
            if ([string]$dataset.acquisition.method -eq 'http-site-mirror') {
                & (Join-Path $PSScriptRoot 'acquire-site-mirror.ps1') -DatasetId $datasetId
            } else {
                & (Join-Path $PSScriptRoot 'acquire-dataset.ps1') -DatasetId $datasetId -Extract
            }
            if ($LASTEXITCODE -ne 0) { throw "Acquisition failed for '$datasetId'." }
        }

        if (-not (Test-Path -LiteralPath (Join-Path $processed 'corpus-manifest.json') -PathType Leaf)) {
            Write-ExpansionStatus -State 'indexing' -DatasetId $datasetId -Completed $index -Message 'Parsing structured documentation and building BM25.'
            $extracted = Join-Path $raw 'extracted'
            $sourceRoot = if (Test-Path -LiteralPath $extracted -PathType Container) { $extracted } else { $raw }
            $arguments = @{DatasetId = $datasetId; SourceRoot = $sourceRoot}
            if ($Force) { $arguments.Force = $true }
            & (Join-Path $PSScriptRoot 'run-documentation-pilot.ps1') @arguments
            if ($LASTEXITCODE -ne 0) { throw "Documentation import failed for '$datasetId'." }
        } elseif (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
            throw "Processed corpus exists without its BM25 database for '$datasetId'; inspect before rebuilding."
        }
        Write-ExpansionStatus -State 'running' -DatasetId $datasetId -Completed ($index + 1) -Message 'Corpus acquired, parsed, indexed, and validated.'
    }
    Write-ExpansionStatus -State 'complete' -DatasetId $null -Completed $DatasetIds.Count -Message 'Documentation expansion completed.'
} catch {
    Write-ExpansionStatus -State 'failed' -DatasetId $datasetId -Completed $index -Message $_.Exception.Message
    throw
}
