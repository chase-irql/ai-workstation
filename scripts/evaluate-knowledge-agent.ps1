[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Suite,
    [string]$ModelId,
    [string]$CaseId,
    [string]$ReplayDirectory,
    [switch]$Unload
)

function ConvertTo-AnswerComparisonTokens {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Text)

    $normalized = $Text.Normalize([Text.NormalizationForm]::FormKC).ToLowerInvariant()
    $normalized = $normalized -replace "(?<=\p{L})['’]s\b", ''
    foreach ($match in [regex]::Matches($normalized, '[\p{L}\p{Nd}]+')) {
        $token = $match.Value
        if ($token.Length -gt 5 -and $token.EndsWith('ing', [StringComparison]::Ordinal)) {
            $token = $token.Substring(0, $token.Length - 3)
        }
        elseif ($token.Length -gt 4 -and $token.EndsWith('ed', [StringComparison]::Ordinal)) {
            $token = $token.Substring(0, $token.Length - 2)
        }
        elseif ($token.Length -gt 3 -and $token.EndsWith('s', [StringComparison]::Ordinal) -and
                -not $token.EndsWith('ss', [StringComparison]::Ordinal)) {
            $token = $token.Substring(0, $token.Length - 1)
        }
        if ($token.Length -gt 4 -and $token.EndsWith('e', [StringComparison]::Ordinal)) {
            $token = $token.Substring(0, $token.Length - 1)
        }
        $token
    }
}

function Test-AnswerContainsTerm {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Answer,
        [Parameter(Mandatory)][string]$ExpectedTerm
    )

    $answerTokens = @(ConvertTo-AnswerComparisonTokens -Text $Answer)
    $expectedTokens = @(ConvertTo-AnswerComparisonTokens -Text $ExpectedTerm)
    if ($expectedTokens.Count -eq 0) { return $false }
    for ($start = 0; $start -le $answerTokens.Count - $expectedTokens.Count; $start++) {
        $matches = $true
        for ($offset = 0; $offset -lt $expectedTokens.Count; $offset++) {
            if ($answerTokens[$start + $offset] -cne $expectedTokens[$offset]) {
                $matches = $false
                break
            }
        }
        if ($matches) { return $true }
    }

    # Treat punctuation-only compound variation as equivalent while preserving
    # contiguous phrase order (for example, "non-complementary" and
    # "noncomplementary"). The ordinary token phrase match above remains the
    # stricter first choice.
    $compactAnswer = $answerTokens -join ''
    $compactExpected = $expectedTokens -join ''
    if ($compactExpected.Length -gt 0 -and
        $compactAnswer.Contains($compactExpected, [StringComparison]::Ordinal)) {
        return $true
    }
    return $false
}

function Test-AnswerContainsUrl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Answer,
        [Parameter(Mandatory)][string]$ExpectedUrl
    )

    $base = $ExpectedUrl.TrimEnd('/')
    return [regex]::IsMatch($Answer, [regex]::Escape($base) + '/?(?=[>\)\]\s]|$)')
}

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-ModelRegistry
if (-not $ModelId) {
    $selected = @($registry.models | Where-Object role -eq 'general-agent' | Sort-Object priority | Select-Object -First 1)
    if ($selected.Count -ne 1) { throw 'No default general-agent model is defined in config/models.json.' }
    $ModelId = $selected[0].id
}
$model = Get-ModelDefinition -ModelId $ModelId
$suiteCandidate = if ([System.IO.Path]::IsPathRooted($Suite)) { $Suite } else { Join-Path $root $Suite }
$suitePath = [System.IO.Path]::GetFullPath($suiteCandidate)
if (-not (Test-Path -LiteralPath $suitePath -PathType Leaf)) { throw "Suite not found: $suitePath" }
$definition = Get-Content -LiteralPath $suitePath -Raw | ConvertFrom-Json
if ($definition.schema_version -ne 1 -or @($definition.cases).Count -lt 1) {
    throw 'Knowledge-agent suites must use schema version 1 and contain at least one case.'
}
$selectedCases = @($definition.cases)
if ($CaseId) {
    $selectedCases = @($selectedCases | Where-Object id -eq $CaseId)
    if ($selectedCases.Count -ne 1) { throw "Unknown or duplicate evaluation case: $CaseId" }
}

$replayRoot = $null
$replayReport = $null
if ($ReplayDirectory) {
    $replayCandidate = if ([System.IO.Path]::IsPathRooted($ReplayDirectory)) {
        $ReplayDirectory
    }
    else {
        Join-Path $root $ReplayDirectory
    }
    $replayRoot = [System.IO.Path]::GetFullPath($replayCandidate)
    if (-not (Test-Path -LiteralPath $replayRoot -PathType Container)) {
        throw "Replay directory not found: $replayRoot"
    }
    $replayReportPath = Join-Path $replayRoot 'report.json'
    if (-not (Test-Path -LiteralPath $replayReportPath -PathType Leaf)) {
        throw "Replay report not found: $replayReportPath"
    }
    $replayReport = Get-Content -LiteralPath $replayReportPath -Raw | ConvertFrom-Json
    if ([string]$replayReport.model_id -ne $ModelId) {
        throw "Replay model '$($replayReport.model_id)' does not match requested model '$ModelId'."
    }
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
New-Item -ItemType Directory -Force -Path $env:OPENCODE_CONFIG_DIR, $env:XDG_CONFIG_HOME | Out-Null

$caseResults = @()
$started = Get-Date
try {
    foreach ($case in $selectedCases) {
        $rawLog = Join-Path $runDirectory "$($case.id).jsonl"
        $caseStarted = Get-Date
        if ($replayRoot) {
            $sourceLog = Join-Path $replayRoot "$($case.id).jsonl"
            if (-not (Test-Path -LiteralPath $sourceLog -PathType Leaf)) {
                throw "Replay log not found for case '$($case.id)': $sourceLog"
            }
            $priorCase = @($replayReport.results | Where-Object id -eq $case.id)
            if ($priorCase.Count -ne 1) {
                throw "Replay report must contain exactly one result for case '$($case.id)'."
            }
            $lines = @(Get-Content -LiteralPath $sourceLog)
            $harnessExitCode = [int]$priorCase[0].harness_exit_code
        }
        else {
            $lines = @(& opencode run --pure --format json --dir $root -m "ollama/$($model.ollama_model)" $case.prompt 2>&1)
            $harnessExitCode = $LASTEXITCODE
        }
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
        $retrievedCorpora = @()
        $answer = ''
        $maximumInputTokens = 0L
        $outputTokens = 0L
        foreach ($event in $events) {
            if ($event.type -eq 'tool_use') {
                $toolName = [string]$event.part.tool
                $toolName = $toolName -replace '^offline-knowledge_', '' -replace '^offline-wikipedia_', ''
                $tools += $toolName
                if ($event.part.state.status -ne 'completed') { $failedTools++ }
                if ($event.part.state.status -eq 'completed') {
                    try {
                        $toolOutput = $event.part.state.output | ConvertFrom-Json
                        if ($toolName -eq 'search_knowledge') {
                            $retrievedDocuments += @($toolOutput.results | ForEach-Object document_id)
                            $retrievedCorpora += @($toolOutput.results | ForEach-Object knowledge_corpus)
                        }
                        elseif ($toolOutput.document_id) {
                            $retrievedDocuments += [string]$toolOutput.document_id
                            if ($toolOutput.knowledge_corpus) { $retrievedCorpora += [string]$toolOutput.knowledge_corpus }
                            elseif ($toolOutput.corpus) { $retrievedCorpora += [string]$toolOutput.corpus }
                        }
                    }
                    catch { }
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
        $missingCorpora = @($case.expected_corpora | Where-Object { $_ -notin $retrievedCorpora })
        $missingCitationUrls = @($case.required_citation_urls | Where-Object {
            -not (Test-AnswerContainsUrl -Answer $answer -ExpectedUrl ([string]$_))
        })
        $missingConcepts = @()
        foreach ($concept in @($case.expected_answer_concepts)) {
            $matched = $false
            foreach ($alternative in @($concept.alternatives)) {
                if (Test-AnswerContainsTerm -Answer $answer -ExpectedTerm ([string]$alternative)) {
                    $matched = $true
                    break
                }
            }
            if (-not $matched) { $missingConcepts += [string]$concept.id }
        }
        $citationReferencePresent = $answer -match '\[S\d+\]'
        $passed = (
            $harnessExitCode -eq 0 -and
            $failedTools -eq 0 -and
            $missingTools.Count -eq 0 -and
            $missingDocuments.Count -eq 0 -and
            $missingCorpora.Count -eq 0 -and
            $missingCitationUrls.Count -eq 0 -and
            $missingConcepts.Count -eq 0 -and
            $citationReferencePresent
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
            retrieved_corpora = @($retrievedCorpora | Select-Object -Unique)
            missing_tools = $missingTools
            missing_document_ids = $missingDocuments
            missing_corpora = $missingCorpora
            missing_citation_urls = $missingCitationUrls
            missing_answer_concepts = $missingConcepts
            citation_reference_present = $citationReferencePresent
            maximum_input_tokens = $maximumInputTokens
            output_tokens = $outputTokens
            answer = $answer
            raw_log = $rawLog
        }
    }
}
finally {
    if ($Unload -and -not $replayRoot) { & ollama stop $model.ollama_model | Out-Null }
}

$report = [ordered]@{
    schema_version = 1
    suite = $definition.name
    suite_path = $suitePath
    model_id = $ModelId
    ollama_model = $model.ollama_model
    answer_matcher = 'normalized_token_phrase_compound_v2'
    replayed_from = if ($replayRoot) { $replayRoot } else { $null }
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
