[CmdletBinding()]
param(
    [ValidateSet('codex', 'opencode', 'all')][string]$Harness = 'all',
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$database = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$pythonPath = Join-Path $root 'rag\src'
$openCodeConfig = Join-Path $root 'opencode.json'

foreach ($requiredPath in @($python, $database)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

if ($Harness -in @('codex', 'all')) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        throw 'Codex CLI was not found on PATH.'
    }

    $existing = & codex mcp get offline-wikipedia 2>$null
    $codexExists = $LASTEXITCODE -eq 0
    if ($codexExists) {
        $expected = ($existing -join "`n") -match [regex]::Escape($database)
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
        & codex mcp add offline-wikipedia --env "PYTHONPATH=$pythonPath" -- $python -m offline_rag.mcp_server --database $database
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
