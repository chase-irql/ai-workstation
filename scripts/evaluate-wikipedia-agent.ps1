[CmdletBinding()]
param(
    [string]$ModelId,
    [string]$Suite = 'rag\eval\wikipedia-agent-v1.json',
    [string]$CaseId,
    [switch]$Unload
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-ModelRegistry
if (-not $ModelId) {
    $selected = @($registry.models | Where-Object role -eq 'general-agent' | Sort-Object priority | Select-Object -First 1)
    if ($selected.Count -ne 1) { throw 'No default general-agent model is defined in config/models.json.' }
    $ModelId = $selected[0].id
}
$model = Get-ModelDefinition -ModelId $ModelId
$suitePath = [System.IO.Path]::GetFullPath((Join-Path $root $Suite))
if (-not (Test-Path -LiteralPath $suitePath -PathType Leaf)) { throw "Suite not found: $suitePath" }
$definition = Get-Content -LiteralPath $suitePath -Raw | ConvertFrom-Json
if ($definition.schema_version -ne 1 -or @($definition.cases).Count -lt 1) {
    throw 'Agent evaluation suite must use schema version 1 and contain at least one case.'
}
$selectedCases = @($definition.cases)
if ($CaseId) {
    $selectedCases = @($selectedCases | Where-Object id -eq $CaseId)
    if ($selectedCases.Count -ne 1) { throw "Unknown or duplicate evaluation case: $CaseId" }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runDirectory = Join-Path $root "results\rag\agent-e2e\$stamp-$ModelId"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$env:OPENCODE_CONFIG = Join-Path $root 'config\harnesses\opencode.json'
$env:OPENCODE_CONFIG_DIR = Join-Path $root 'runtime\opencode-rag-config'
$env:XDG_CONFIG_HOME = Join-Path $root 'runtime\xdg-rag-config'
$env:OPENCODE_DISABLE_AUTOUPDATE = 'true'
$env:OPENCODE_AUTO_SHARE = 'false'
$env:OPENCODE_DISABLE_CLAUDE_CODE = '1'
New-Item -ItemType Directory -Force -Path $env:OPENCODE_CONFIG_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:XDG_CONFIG_HOME | Out-Null

$caseResults = @()
$started = Get-Date
try {
    foreach ($case in $selectedCases) {
        $rawLog = Join-Path $runDirectory "$($case.id).jsonl"
        $caseStarted = Get-Date
        $lines = @(& opencode run --pure --format json --dir $root -m "ollama/$($model.ollama_model)" $case.prompt 2>&1)
        $harnessExitCode = $LASTEXITCODE
        $lines | Set-Content -LiteralPath $rawLog -Encoding UTF8

        $events = @()
        foreach ($line in $lines) {
            if ([string]$line -match '^\s*\{') {
                try { $events += ([string]$line | ConvertFrom-Json) } catch { }
            }
        }
        $tools = @()
        $failedTools = 0
        $retrievedDocuments = @()
        $answer = ''
        $maximumInputTokens = 0L
        $outputTokens = 0L
        foreach ($event in $events) {
            if ($event.type -eq 'tool_use') {
                $toolName = [string]$event.part.tool -replace '^offline-wikipedia_', ''
                $tools += $toolName
                if ($event.part.state.status -ne 'completed') { $failedTools++ }
                if ($toolName -eq 'search_wikipedia' -and $event.part.state.status -eq 'completed') {
                    try {
                        $searchOutput = $event.part.state.output | ConvertFrom-Json
                        $retrievedDocuments += @($searchOutput.results | ForEach-Object document_id)
                    } catch { }
                }
            }
            elseif ($event.type -eq 'text') {
                $answer = [string]$event.part.text
            }
            elseif ($event.type -eq 'step_finish' -and $event.part.tokens) {
                $maximumInputTokens = [math]::Max($maximumInputTokens, [long]$event.part.tokens.input)
                $outputTokens += [long]$event.part.tokens.output
            }
        }

        $missingTools = @($case.required_tools | Where-Object { $_ -notin $tools })
        $missingDocuments = @($case.expected_document_ids | Where-Object { $_ -notin $retrievedDocuments })
        $missingTerms = @($case.expected_answer_terms | Where-Object { $answer -notmatch [regex]::Escape($_) })
        $hasCitation = $answer -match 'Wikipedia\s+[—-].*https://en\.wikipedia\.org/wiki/'
        $passed = (
            $harnessExitCode -eq 0 -and
            $failedTools -eq 0 -and
            $missingTools.Count -eq 0 -and
            $missingDocuments.Count -eq 0 -and
            $missingTerms.Count -eq 0 -and
            $hasCitation
        )
        $caseResults += [ordered]@{
            id = $case.id
            passed = $passed
            wall_seconds = [math]::Round(((Get-Date) - $caseStarted).TotalSeconds, 3)
            harness_exit_code = $harnessExitCode
            tool_calls = $tools.Count
            tools = $tools
            failed_tool_calls = $failedTools
            retrieved_document_ids = @($retrievedDocuments | Select-Object -Unique)
            missing_tools = $missingTools
            missing_document_ids = $missingDocuments
            missing_answer_terms = $missingTerms
            citation_present = $hasCitation
            maximum_input_tokens = $maximumInputTokens
            output_tokens = $outputTokens
            answer = $answer
            raw_log = $rawLog
        }
    }
}
finally {
    if ($Unload) { & ollama stop $model.ollama_model | Out-Null }
}

$report = [ordered]@{
    schema_version = 1
    suite = $definition.name
    suite_path = $suitePath
    model_id = $ModelId
    ollama_model = $model.ollama_model
    started_at = $started.ToString('o')
    finished_at = (Get-Date).ToString('o')
    cases = $caseResults.Count
    passed_cases = @($caseResults | Where-Object passed).Count
    passed = @($caseResults | Where-Object { -not $_.passed }).Count -eq 0
    results = $caseResults
}
$reportPath = Join-Path $runDirectory 'report.json'
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 12
if (-not $report.passed) { exit 2 }
