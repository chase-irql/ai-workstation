[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$pidPath = Join-Path $root 'runtime\wikipedia-service\service.pid'
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    Write-Output 'Wikipedia service is not running (no PID file).'
    exit 0
}

$recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidPath -Force
    Write-Output "Removed stale Wikipedia service PID file ($recordedPid)."
    exit 0
}
if ($process.CommandLine -notmatch 'offline_rag\.service') {
    throw "Refusing to stop PID $recordedPid because it is not the Wikipedia service."
}

Stop-Process -Id $recordedPid
Remove-Item -LiteralPath $pidPath -Force
Write-Output "Stopped Wikipedia service PID $recordedPid."
