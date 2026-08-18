[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{8}$')][string]$PreviousDumpDate,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{8}$')][string]$DumpDate,
    [ValidateRange(1, 16)][int]$MaxChunks = 1,
    [ValidateRange(1, 1000000)][int]$MaxCharacters = 4000,
    [ValidateRange(0, 1000)][int]$SampleLimit = 20,
    [string]$Output
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$previousDatabase = Join-Path $root "indexes\wikipedia\enwiki-$PreviousDumpDate-full.sqlite3"
$newDatabase = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$env:PYTHONPATH = Join-Path $root 'rag\src'

if ($PreviousDumpDate -eq $DumpDate) { throw 'PreviousDumpDate and DumpDate must differ.' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python virtual environment not found: $python" }
if (-not (Test-Path -LiteralPath $previousDatabase -PathType Leaf)) {
    throw "Previous Wikipedia database not found: $previousDatabase"
}
if (-not (Test-Path -LiteralPath $newDatabase -PathType Leaf)) {
    throw "New Wikipedia database not found: $newDatabase"
}
if (-not $Output) {
    $Output = Join-Path $root "runtime\wikipedia-update\enwiki-$PreviousDumpDate-to-$DumpDate.json"
}

& $python -m offline_rag.corpus_update plan `
    --previous-database $previousDatabase `
    --new-database $newDatabase `
    --max-chunks $MaxChunks `
    --max-characters $MaxCharacters `
    --sample-limit $SampleLimit `
    --output $Output
exit $LASTEXITCODE
