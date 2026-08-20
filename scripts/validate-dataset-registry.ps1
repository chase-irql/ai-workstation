[CmdletBinding()]
param(
    [string]$Registry = 'config\datasets.json',
    [string]$PythonExecutable
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
if (-not $PythonExecutable) {
    $localPython = Join-Path $root '.venv\Scripts\python.exe'
    $PythonExecutable = if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $localPython
    }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if (-not $command) { throw 'Python was not found. Create .venv or pass -PythonExecutable.' }
        $command.Source
    }
}
$python = [System.IO.Path]::GetFullPath($PythonExecutable)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python executable not found: $python"
}
$env:PYTHONPATH = Join-Path $root 'rag\src'
$registryCandidate = if ([System.IO.Path]::IsPathRooted($Registry)) { $Registry } else { Join-Path $root $Registry }
$registryPath = [System.IO.Path]::GetFullPath($registryCandidate)
& $python -m offline_rag.dataset_registry --registry $registryPath
if ($LASTEXITCODE -ne 0) { throw 'Dataset registry validation failed.' }
