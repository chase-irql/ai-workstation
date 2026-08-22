[CmdletBinding()]
param(
    [ValidateSet('codex', 'opencode', 'all')][string]$Harness = 'all',
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801',
    [ValidateSet('bm25', 'semantic', 'hybrid')][string]$WikipediaRetrieval = 'hybrid',
    [ValidateRange(0, 4096)][int]$QueryCacheSize = 256,
    [string]$ModelId,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$pythonPath = Join-Path $root 'rag\src'
$models = Join-Path $root 'config\models.json'
$registryPath = Join-Path $root 'config\datasets.json'
$openCodeConfig = Join-Path $root 'opencode.json'
$wikipediaDatabase = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-full.sqlite3"
$wikipediaVectors = Join-Path $root "indexes\wikipedia\enwiki-$DumpDate-semantic-full"

foreach ($requiredPath in @($python, $models, $registryPath, $wikipediaDatabase)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

$registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
$evaluated = @($registry.datasets | Where-Object { $_.status -eq 'evaluated' })
if ($evaluated.Count -eq 0) { throw 'No evaluated datasets are registered.' }

$mcpCommand = @(
    $python,
    '-m', 'offline_rag.knowledge_mcp_server',
    '--index', "wikipedia=$wikipediaDatabase"
)
$semanticMappings = @()
$queryAliasMappings = @()
$relaxationMappings = @()
$queryRouteMappings = @()
foreach ($dataset in $evaluated) {
    $database = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.index)))
    if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
        throw "Dataset '$($dataset.dataset_id)' is marked evaluated but its index is missing: $database"
    }
    $mcpCommand += @('--index', "$($dataset.dataset_id)=$database")
    if ($dataset.PSObject.Properties['ingestion'] -and $dataset.ingestion.PSObject.Properties['query_aliases']) {
        foreach ($alias in @($dataset.ingestion.query_aliases)) {
            if (-not $alias.from -or -not $alias.to) {
                throw "Dataset '$($dataset.dataset_id)' has an invalid ingestion.query_aliases entry."
            }
            $queryAliasMappings += @('--query-alias', "$($dataset.dataset_id)=$([string]$alias.from)=>$([string]$alias.to)")
        }
    }
    if ($dataset.PSObject.Properties['ingestion'] -and
            $dataset.ingestion.PSObject.Properties['relax_bm25_on_empty'] -and
            [bool]$dataset.ingestion.relax_bm25_on_empty) {
        $relaxationMappings += @('--relax-bm25-on-empty', [string]$dataset.dataset_id)
    }
    if ($dataset.PSObject.Properties['ingestion'] -and $dataset.ingestion.PSObject.Properties['query_routes']) {
        foreach ($pattern in @($dataset.ingestion.query_routes)) {
            if (-not $pattern) { throw "Dataset '$($dataset.dataset_id)' has an empty ingestion.query_routes entry." }
            $queryRouteMappings += @('--query-route', "$($dataset.dataset_id)=$([string]$pattern)")
        }
    }
    if ($dataset.paths.PSObject.Properties['semantic_index']) {
        $semantic = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$dataset.paths.semantic_index)))
        if (Test-Path -LiteralPath (Join-Path $semantic 'manifest.json') -PathType Leaf) {
            $semanticMappings += @('--corpus-vector', "$($dataset.dataset_id)=$semantic")
        }
    }
}
$mcpCommand += $queryAliasMappings
$mcpCommand += $relaxationMappings
$mcpCommand += $queryRouteMappings

if ($WikipediaRetrieval -ne 'bm25') {
    if (-not (Test-Path -LiteralPath (Join-Path $wikipediaVectors 'manifest.json') -PathType Leaf)) {
        throw "Published Wikipedia semantic generation not found: $wikipediaVectors"
    }
    $semanticMappings = @('--corpus-vector', "wikipedia=$wikipediaVectors") + $semanticMappings
}
if ($semanticMappings.Count) {
    $mcpCommand += $semanticMappings
    $mcpCommand += @(
        '--models', $models,
        '--default-vector-retrieval', $WikipediaRetrieval,
        '--query-cache-size', "$QueryCacheSize"
    )
    if ($ModelId) { $mcpCommand += @('--model-id', $ModelId) }
}

function Test-CommandEqual([object[]]$Actual, [object[]]$Expected) {
    if ($Actual.Count -ne $Expected.Count) { return $false }
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        if ([string]$Actual[$index] -cne [string]$Expected[$index]) { return $false }
    }
    return $true
}

function Convert-ToProjectRelativeArgument([string]$Value) {
    $prefix = ''
    $candidate = $Value
    $separator = $Value.IndexOf('=')
    if ($separator -gt 0) {
        $prefix = $Value.Substring(0, $separator + 1)
        $candidate = $Value.Substring($separator + 1)
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) { return $Value }
    $resolved = [System.IO.Path]::GetFullPath($candidate)
    $rootPrefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $Value
    }
    $relative = [System.IO.Path]::GetRelativePath($root, $resolved)
    if (-not $prefix -and $relative -eq '.venv\Scripts\python.exe') { $relative = ".\$relative" }
    return "$prefix$relative"
}

$openCodeMcpCommand = @($mcpCommand | ForEach-Object { Convert-ToProjectRelativeArgument ([string]$_) })
$openCodePythonPath = [System.IO.Path]::GetRelativePath($root, $pythonPath)

if ($Harness -in @('codex', 'all')) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'Codex CLI was not found on PATH.' }
    $existing = & codex mcp get offline-knowledge 2>$null
    $exists = $LASTEXITCODE -eq 0
    if ($exists -and -not $Force) {
        $existingText = $existing -join "`n"
        $missingArgument = @($mcpCommand | Where-Object { $existingText -notmatch [regex]::Escape([string]$_) })
        if ($missingArgument.Count) {
            throw 'Codex offline-knowledge settings differ. Re-run with -Force to replace them.'
        }
        Write-Output 'Codex MCP server offline-knowledge is already configured.'
    }
    if ($exists -and $Force) {
        & codex mcp remove offline-knowledge
        if ($LASTEXITCODE -ne 0) { throw 'Failed to remove the existing Codex knowledge MCP configuration.' }
        $exists = $false
    }
    if (-not $exists) {
        $arguments = @('mcp', 'add', 'offline-knowledge', '--env', "PYTHONPATH=$pythonPath", '--') + $mcpCommand
        & codex @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Failed to configure the Codex knowledge MCP server.' }
    }
    & codex mcp get offline-knowledge
    if ($LASTEXITCODE -ne 0) { throw 'Codex could not read back the knowledge MCP configuration.' }
}

if ($Harness -in @('opencode', 'all')) {
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) { throw 'OpenCode was not found on PATH.' }
    if (-not (Test-Path -LiteralPath $openCodeConfig -PathType Leaf)) {
        throw "OpenCode project configuration was not found: $openCodeConfig"
    }
    $configuration = Get-Content -LiteralPath $openCodeConfig -Raw | ConvertFrom-Json
    if (-not $configuration.mcp) { $configuration | Add-Member -NotePropertyName mcp -NotePropertyValue ([pscustomobject]@{}) }
    $configurationChanged = $false
    $entry = $configuration.mcp.'offline-knowledge'
    if ($entry -and -not (Test-CommandEqual @($entry.command) $openCodeMcpCommand) -and -not $Force) {
        throw 'OpenCode offline-knowledge settings differ. Re-run with -Force to replace them.'
    }
    if (-not $entry -or -not (Test-CommandEqual @($entry.command) $openCodeMcpCommand)) {
        $newEntry = [pscustomobject]@{
            type = 'local'
            command = [object[]]$openCodeMcpCommand
            environment = [pscustomobject]@{ PYTHONPATH = $openCodePythonPath }
            enabled = $true
            timeout = 30000
        }
        if ($entry) {
            $configuration.mcp.'offline-knowledge' = $newEntry
        }
        else {
            $configuration.mcp | Add-Member -NotePropertyName 'offline-knowledge' -NotePropertyValue $newEntry
        }
        $configurationChanged = $true
    }
    $legacyEntry = $configuration.mcp.'offline-wikipedia'
    if ($legacyEntry -and (-not $legacyEntry.PSObject.Properties['enabled'] -or $legacyEntry.enabled -ne $false)) {
        if ($legacyEntry.PSObject.Properties['enabled']) {
            $legacyEntry.enabled = $false
        }
        else {
            $legacyEntry | Add-Member -NotePropertyName enabled -NotePropertyValue $false
        }
        $configurationChanged = $true
    }
    if ($configurationChanged) {
        $temporary = "$openCodeConfig.tmp"
        $configuration | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $openCodeConfig -Force
    }
    Push-Location $root
    try {
        $resolved = & opencode debug config
        if ($LASTEXITCODE -ne 0 -or ($resolved -join "`n") -notmatch 'offline-knowledge') {
            throw 'OpenCode did not resolve the offline-knowledge MCP configuration.'
        }
        & opencode mcp list
        if ($LASTEXITCODE -ne 0) { throw 'OpenCode could not start the knowledge MCP server.' }
    }
    finally {
        Pop-Location
    }
}
