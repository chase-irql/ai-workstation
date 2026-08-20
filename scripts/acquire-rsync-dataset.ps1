[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [Parameter(Mandatory)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$Snapshot,
    [string]$Distribution = 'Ubuntu'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $root 'rag\src'
& $python -m offline_rag.rsync_acquisition `
    --registry (Join-Path $root 'config\datasets.json') `
    --dataset $DatasetId `
    --project-root $root `
    --snapshot $Snapshot `
    --distribution $Distribution
if ($LASTEXITCODE -ne 0) { throw "Rsync dataset acquisition failed: $DatasetId" }
