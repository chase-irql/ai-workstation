[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DatasetId,
    [switch]$Extract
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$env:PYTHONPATH = Join-Path $root 'rag\src'
$arguments = @(
    '-m', 'offline_rag.acquisition',
    '--registry', (Join-Path $root 'config\datasets.json'),
    '--dataset', $DatasetId,
    '--project-root', $root
)
if ($Extract) { $arguments += '--extract' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Dataset acquisition failed: $DatasetId" }
