[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$env:PYTHONPATH = Join-Path $root 'rag\src'
$arguments = @(
    '-m', 'offline_rag.site_mirror',
    '--registry', (Join-Path $root 'config\datasets.json'),
    '--dataset', $DatasetId,
    '--project-root', $root
)
if ($Force) { $arguments += '--force' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Site mirror acquisition failed: $DatasetId" }
