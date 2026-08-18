[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateRange(10, 600)][int]$PollSeconds = 30,
    [string]$DiscordUserId = ''
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$processed = Join-Path $root "corpora\processed\wikipedia\enwiki-$DumpDate\full"
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$runtime = Join-Path $root 'runtime\wikipedia-full'
$failureLog = Join-Path $runtime 'failure.log'
$verificationLog = Join-Path $runtime 'verification.log'
$verificationResult = Join-Path $runtime 'verification.json'
$evaluationResult = Join-Path $runtime 'evaluation-full.json'
$watcherStatus = Join-Path $runtime 'watcher-status.json'
$webhook = $env:WIKI_DISCORD_WEBHOOK
if (-not $webhook) {
    $webhook = [Environment]::GetEnvironmentVariable('WIKI_DISCORD_WEBHOOK', 'User')
}
$env:PYTHONPATH = Join-Path $root 'rag\src'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Send-DiscordNotification([string]$Message) {
    if (-not $webhook) { return }
    $content = if ($DiscordUserId) { "<@$DiscordUserId> $Message" } else { $Message }
    # The explicit object-array cast prevents PowerShell's pipeline unrolling
    # from serializing a single Discord user ID as a JSON string.
    $mentions = if ($DiscordUserId) { [object[]]@($DiscordUserId) } else { [object[]]@() }
    $body = @{ content = $content; allowed_mentions = @{ users = $mentions } } | ConvertTo-Json -Depth 4
    try {
        Invoke-RestMethod -Uri $webhook -Method Post -ContentType 'application/json' -Body $body | Out-Null
    }
    catch {
        "Discord notification failed: $_" | Add-Content -LiteralPath $verificationLog
    }
}

function Write-WatcherStatus([string]$State, [string]$Message) {
    $value = @{
        state = $State
        message = $Message
        updated_at = [DateTimeOffset]::Now.ToString('o')
        watcher_pid = $PID
    } | ConvertTo-Json
    $temporary = "$watcherStatus.tmp"
    Set-Content -LiteralPath $temporary -Value $value -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $watcherStatus -Force
}

try {
    Write-WatcherStatus 'waiting' 'Waiting for the Wikipedia pipeline wrapper to finish.'
    while ($true) {
        $pipeline = Get-CimInstance Win32_Process | Where-Object {
            $_.ProcessId -ne $PID -and $_.CommandLine -match 'run-wikipedia-full\.ps1'
        }
        if (-not $pipeline) { break }
        Start-Sleep -Seconds $PollSeconds
    }

    if (Test-Path -LiteralPath $failureLog) {
        throw "Wikipedia pipeline failure log exists: $failureLog"
    }
    if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
        throw "Wikipedia pipeline stopped without publishing its database: $database"
    }

    Write-WatcherStatus 'verifying' 'Database published; running independent verification.'
    Send-DiscordNotification 'Wikipedia database build completed. Independent verification has started; no action is needed yet.'
    "Verification started: $([DateTimeOffset]::Now.ToString('o'))" | Set-Content -LiteralPath $verificationLog

    & $python -m pytest -q (Join-Path $root 'rag\tests') 2>&1 | Tee-Object -FilePath $verificationLog -Append
    if ($LASTEXITCODE -ne 0) { throw 'Repository tests failed.' }

    & $python -m compileall -q (Join-Path $root 'rag\src') (Join-Path $root 'rag\tests') `
        2>&1 | Tee-Object -FilePath $verificationLog -Append
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation checks failed.' }

    & $python -m offline_rag.verify --database $database --input $processed --output $verificationResult `
        2>&1 | Tee-Object -FilePath $verificationLog -Append
    if ($LASTEXITCODE -ne 0) { throw 'Database integrity or smoke-query verification failed.' }

    & $python -m offline_rag.evaluate --database $database `
        --suite (Join-Path $root 'rag\eval\wikipedia-full-v2.json') --output $evaluationResult `
        2>&1 | Tee-Object -FilePath $verificationLog -Append
    if ($LASTEXITCODE -ne 0) { throw 'Retrieval evaluation failed to run.' }

    $evaluation = Get-Content -Raw -LiteralPath $evaluationResult | ConvertFrom-Json
    $successAt5 = [double]$evaluation.aggregate.success_at_5
    $mrrAt10 = [double]$evaluation.aggregate.mrr_at_10
    if ($successAt5 -lt 0.75 -or $mrrAt10 -lt 0.5) {
        throw "Retrieval quality below threshold: Success@5=$successAt5, MRR@10=$mrrAt10"
    }

    $verification = Get-Content -Raw -LiteralPath $verificationResult | ConvertFrom-Json
    $message = "Wikipedia retrieval verified: $($verification.documents) documents, $($verification.chunks) chunks, Success@5=$successAt5, MRR@10=$mrrAt10. The system is ready."
    Write-WatcherStatus 'complete' $message
    Send-DiscordNotification $message
    [Environment]::SetEnvironmentVariable('WIKI_DISCORD_WEBHOOK', $null, 'User')
    $message | Add-Content -LiteralPath $verificationLog
    exit 0
}
catch {
    $message = "Wikipedia verification needs attention: $($_.Exception.Message) Return to the PC and continue prompting Codex; details: $verificationLog"
    Write-WatcherStatus 'failed' $message
    $message | Add-Content -LiteralPath $verificationLog
    Send-DiscordNotification $message
    [Environment]::SetEnvironmentVariable('WIKI_DISCORD_WEBHOOK', $null, 'User')
    exit 1
}
