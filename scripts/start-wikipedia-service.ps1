[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [string]$ListenAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$Background
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$runtime = Join-Path $root 'runtime\wikipedia-service'
$pidPath = Join-Path $runtime 'service.pid'
$stdoutPath = Join-Path $runtime 'service.stdout.log'
$stderrPath = Join-Path $runtime 'service.stderr.log'
$env:PYTHONPATH = Join-Path $root 'rag\src'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment not found: $python"
}
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "Published Wikipedia database not found: $database"
}

$arguments = @(
    '-m', 'offline_rag.service',
    '--database', $database,
    '--host', $ListenAddress,
    '--port', "$Port"
)

if (-not $Background) {
    & $python @arguments
    exit $LASTEXITCODE
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (Test-Path -LiteralPath $pidPath) {
    $recordedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine -match 'offline_rag\.service') {
        throw "Wikipedia service is already running as PID $recordedPid."
    }
    Remove-Item -LiteralPath $pidPath -Force
}

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
Set-Content -LiteralPath "$pidPath.tmp" -Value $process.Id -Encoding ascii
Move-Item -LiteralPath "$pidPath.tmp" -Destination $pidPath -Force

$healthUrl = "http://$($ListenAddress):$Port/health"
$ready = $false
$health = $null
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    if ($process.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($health.status -eq 'ok') {
            $ready = $true
            break
        }
    }
    catch {
        Start-Sleep -Milliseconds 250
    }
}

if ($ready) {
    [ordered]@{
        status = 'ready'
        pid = $process.Id
        url = "http://$($ListenAddress):$Port/"
        documents = $health.index.document_count
        chunks = $health.index.chunk_count
        database = $database
    } | ConvertTo-Json
    return
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
}
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
$details = Get-Content -LiteralPath $stderrPath -Tail 20 -ErrorAction SilentlyContinue
throw "Wikipedia service failed to become ready. $details"
