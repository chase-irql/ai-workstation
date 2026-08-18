[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][int]$BuildPid,
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$runtime = Join-Path $root 'runtime\wikipedia-semantic-full'
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$statusPath = Join-Path $runtime 'verification-status.json'

while (Get-Process -Id $BuildPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 30
}

if ((Test-Path -LiteralPath (Join-Path $vectorDirectory 'manifest.json') -PathType Leaf) -and
    -not (Test-Path -LiteralPath (Join-Path $vectorDirectory '.build-state.json'))) {
    & (Join-Path $PSScriptRoot 'verify-wikipedia-semantic-full.ps1') -DumpDate $DumpDate
    exit $LASTEXITCODE
}

[ordered]@{
    status = 'build_interrupted'
    detected_at = [DateTimeOffset]::Now.ToString('o')
    build_pid = $BuildPid
    resumable = Test-Path -LiteralPath (Join-Path $vectorDirectory '.build-state.json')
    resume_command = '.\scripts\run-wikipedia-semantic-full.ps1 -Resume -Background'
} | ConvertTo-Json | Set-Content -LiteralPath "$statusPath.tmp" -Encoding utf8
Move-Item -LiteralPath "$statusPath.tmp" -Destination $statusPath -Force
exit 2
