[CmdletBinding()]
param(
    [string]$Registry = 'config\datasets.json'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run the RAG virtual-environment setup first.' }
$env:PYTHONPATH = Join-Path $root 'rag\src'
$registryCandidate = if ([System.IO.Path]::IsPathRooted($Registry)) { $Registry } else { Join-Path $root $Registry }
$registryPath = [System.IO.Path]::GetFullPath($registryCandidate)
& $python -m offline_rag.dataset_registry --registry $registryPath
if ($LASTEXITCODE -ne 0) { throw 'Dataset registry validation failed.' }
