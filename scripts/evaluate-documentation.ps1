[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][string]$Suite,
    [string]$Output
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$matches = @($registry.datasets | Where-Object { $_.dataset_id -eq $DatasetId })
if ($matches.Count -ne 1) { throw "Unknown or duplicate dataset ID '$DatasetId'." }
$database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$matches[0].paths.index)))
$suiteCandidate = if ([System.IO.Path]::IsPathRooted($Suite)) { $Suite } else { Join-Path $root $Suite }
$suitePath = [System.IO.Path]::GetFullPath($suiteCandidate)
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw "Index not found: $database" }
if (-not (Test-Path -LiteralPath $suitePath -PathType Leaf)) { throw "Evaluation suite not found: $suitePath" }
if (-not $Output) {
    $Output = Join-Path $root "results\rag\documentation\$DatasetId-evaluation.json"
}
$outputCandidate = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $root $Output }
$outputPath = [System.IO.Path]::GetFullPath($outputCandidate)
& $python -m offline_rag.evaluate --database $database --suite $suitePath --output $outputPath
if ($LASTEXITCODE -ne 0) { throw 'Documentation retrieval evaluation failed.' }
Write-Output "Evaluation report: $outputPath"
