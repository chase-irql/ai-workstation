[CmdletBinding()]
param(
    [ValidateSet('codex', 'opencode', 'all')][string]$Harness = 'all',
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateSet('bm25', 'semantic', 'hybrid')][string]$RetrievalMode = 'bm25',
    [ValidateRange(0, 4096)][int]$QueryCacheSize = 256,
    [string]$ModelId,
    [switch]$EnableSemantic,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$vectorDirectory = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"
$models = Join-Path $root 'config\models.json'
$pythonPath = Join-Path $root 'rag\src'
$openCodeConfig = Join-Path $root 'opencode.json'

foreach ($requiredPath in @($python, $database)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}
$semanticEnabled = $EnableSemantic -or $RetrievalMode -ne 'bm25'
if ($semanticEnabled -and -not (Test-Path -LiteralPath (Join-Path $vectorDirectory 'manifest.json') -PathType Leaf)) {
    throw "Published semantic generation not found: $vectorDirectory"
}
$mcpCommand = @($python, '-m', 'offline_rag.mcp_server', '--database', $database)
if ($semanticEnabled) {
    $mcpCommand += @(
        '--vector-index', $vectorDirectory,
        '--models', $models,
        '--default-retrieval', $RetrievalMode,
        '--query-cache-size', "$QueryCacheSize"
    )
    if ($ModelId) { $mcpCommand += @('--model-id', $ModelId) }
}

if ($Harness -in @('codex', 'all')) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        throw 'Codex CLI was not found on PATH.'
    }

    $existing = & codex mcp get offline-wikipedia 2>$null
    $codexExists = $LASTEXITCODE -eq 0
    if ($codexExists) {
        $existingText = $existing -join "`n"
        $expected = $existingText -match [regex]::Escape($database)
        if ($semanticEnabled) {
            $expected = $expected `
                -and ($existingText -match [regex]::Escape($vectorDirectory)) `
                -and ($existingText -match [regex]::Escape($RetrievalMode))
        }
        else {
            $expected = $expected -and $existingText -notmatch '--vector-index'
        }
        if ($expected -and -not $Force) {
            Write-Output 'Codex MCP server offline-wikipedia is already configured for this index.'
        }
        elseif (-not $Force) {
            throw 'Codex MCP server offline-wikipedia already exists with different settings. Re-run with -Force to replace it.'
        }
        else {
            & codex mcp remove offline-wikipedia
            if ($LASTEXITCODE -ne 0) { throw 'Failed to remove the existing Codex MCP configuration.' }
        }
    }

    if (-not $codexExists -or $Force) {
        $codexArguments = @('mcp', 'add', 'offline-wikipedia', '--env', "PYTHONPATH=$pythonPath", '--') + $mcpCommand
        & codex @codexArguments
        if ($LASTEXITCODE -ne 0) { throw 'Failed to configure the Codex Wikipedia MCP server.' }
    }

    & codex mcp get offline-wikipedia
    if ($LASTEXITCODE -ne 0) { throw 'Codex could not read back the Wikipedia MCP configuration.' }
}

if ($Harness -in @('opencode', 'all')) {
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
        throw 'OpenCode was not found on PATH.'
    }
    if (-not (Test-Path -LiteralPath $openCodeConfig -PathType Leaf)) {
        throw "OpenCode project configuration was not found: $openCodeConfig"
    }
    $configuration = Get-Content -Raw -LiteralPath $openCodeConfig | ConvertFrom-Json
    $entry = $configuration.mcp.'offline-wikipedia'
    if (-not $entry) { throw 'OpenCode configuration has no offline-wikipedia MCP entry.' }
    $currentCommand = @($entry.command)
    $commandMatches = ($currentCommand.Count -eq $mcpCommand.Count)
    if ($commandMatches) {
        for ($index = 0; $index -lt $mcpCommand.Count; $index++) {
            if ([string]$currentCommand[$index] -cne [string]$mcpCommand[$index]) {
                $commandMatches = $false
                break
            }
        }
    }
    if (-not $commandMatches -and -not $Force) {
        throw 'OpenCode offline-wikipedia settings differ. Re-run with -Force to replace them.'
    }
    if (-not $commandMatches) {
        $entry.command = [object[]]$mcpCommand
        $entry.environment.PYTHONPATH = $pythonPath
        $temporaryConfig = "$openCodeConfig.tmp"
        $configuration | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryConfig -Encoding utf8
        Move-Item -LiteralPath $temporaryConfig -Destination $openCodeConfig -Force
    }
    Push-Location $root
    try {
        $resolved = & opencode debug config
        if ($LASTEXITCODE -ne 0 -or ($resolved -join "`n") -notmatch 'offline-wikipedia') {
            throw 'OpenCode did not resolve the offline-wikipedia MCP configuration.'
        }
        & opencode mcp list
        if ($LASTEXITCODE -ne 0) { throw 'OpenCode could not start the Wikipedia MCP server.' }
    }
    finally {
        Pop-Location
    }
}
