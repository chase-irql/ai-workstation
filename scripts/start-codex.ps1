[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-ModelRegistry
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Codex CLI was not found on PATH.'
}

$catalog = Join-Path $root 'config\harnesses\codex-models.json'
$configTemplate = Join-Path $root 'config\harnesses\codex-home\config.toml'
foreach ($requiredFile in @($catalog, $configTemplate)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required Codex configuration was not found: $requiredFile"
    }
}

try {
    $tags = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
    throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama and try again.'
}
$installedModelNames = @($tags.models | ForEach-Object { [string]$_.name })
$modelChoices = @(
    $registry.models |
        Where-Object { $_.role -ne 'embedding' -and $_.ollama_model -in $installedModelNames } |
        Sort-Object priority, id |
        ForEach-Object {
            [pscustomobject]@{
                Id = [string]$_.id
                Display = "$($_.id)  |  $($_.role)  |  $($_.quantization)  |  $($_.ollama_model)"
            }
        }
)
if ($modelChoices.Count -eq 0) {
    throw 'No configured Codex agent models are installed in Ollama. Use scripts\pull-model.ps1 first.'
}

function Read-CodexWorkingDirectory {
    param(
        [Parameter(Mandatory)][string]$DefaultDirectory
    )

    while ($true) {
        $value = Read-Host "Working directory [$DefaultDirectory]"
        $candidate = if ([string]::IsNullOrWhiteSpace($value)) {
            $DefaultDirectory
        }
        else {
            $value.Trim().Trim('"')
        }
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
        Write-Warning "Directory does not exist: $candidate"
    }
}

function Select-ConsoleModel {
    param(
        [Parameter(Mandatory)][object[]]$Models,
        [string]$DefaultModelId
    )

    if ([Console]::IsInputRedirected) {
        throw 'The model selector requires an interactive PowerShell terminal.'
    }
    $selectedIndex = 0
    for ($index = 0; $index -lt $Models.Count; $index++) {
        if ($Models[$index].Id -eq $DefaultModelId) { $selectedIndex = $index; break }
    }

    Write-Host ''
    Write-Host 'Installed local models:'
    foreach ($choice in $Models) { Write-Host "  $($choice.Display)" }
    Write-Host ''
    Write-Host 'Use Up/Down arrows to choose, Enter to launch, or Escape to cancel.'

    $oldCursorVisible = [Console]::CursorVisible
    try {
        [Console]::CursorVisible = $false
        while ($true) {
            $text = "> [$($selectedIndex + 1)/$($Models.Count)] $($Models[$selectedIndex].Display)"
            $maximumWidth = [Math]::Max(20, [Console]::BufferWidth - 1)
            if ($text.Length -gt $maximumWidth) {
                $text = $text.Substring(0, [Math]::Max(1, $maximumWidth - 1)) + '…'
            }
            [Console]::Write("`r" + (' ' * $maximumWidth) + "`r")
            [Console]::ForegroundColor = [ConsoleColor]::Cyan
            [Console]::Write($text)
            [Console]::ResetColor()

            $key = [Console]::ReadKey($true)
            switch ($key.Key) {
                'UpArrow' { $selectedIndex = ($selectedIndex - 1 + $Models.Count) % $Models.Count }
                'LeftArrow' { $selectedIndex = ($selectedIndex - 1 + $Models.Count) % $Models.Count }
                'DownArrow' { $selectedIndex = ($selectedIndex + 1) % $Models.Count }
                'RightArrow' { $selectedIndex = ($selectedIndex + 1) % $Models.Count }
                'Enter' {
                    [Console]::WriteLine()
                    return $Models[$selectedIndex]
                }
                'Escape' {
                    [Console]::WriteLine()
                    return $null
                }
            }
        }
    }
    finally {
        [Console]::ResetColor()
        [Console]::CursorVisible = $oldCursorVisible
    }
}

$defaultModel = @(
    $registry.models |
        Where-Object { $_.role -eq 'general-agent' -and $_.ollama_model -in $installedModelNames } |
        Sort-Object priority, id |
        Select-Object -First 1
)
$WorkingDirectory = Read-CodexWorkingDirectory `
    -DefaultDirectory ([System.IO.Path]::GetFullPath((Get-Location).Path))
$selectedModel = Select-ConsoleModel `
    -Models $modelChoices `
    -DefaultModelId $(if ($defaultModel.Count -eq 1) { [string]$defaultModel[0].id } else { '' })
if (-not $selectedModel) {
    Write-Host 'Local Codex launch cancelled.'
    exit 0
}

$ModelId = $selectedModel.Id
$model = Get-ModelDefinition -ModelId $ModelId

$codexHome = Join-Path $root 'runtime\codex-home'
New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
$tomlEscape = {
    param([string]$Value)
    return $Value.Replace('\', '\\').Replace('"', '\"')
}
$renderedConfig = Get-Content -LiteralPath $configTemplate -Raw
$renderedConfig = $renderedConfig.Replace('__MODEL_ID__', (& $tomlEscape ([string]$model.ollama_model)))
$renderedConfig = $renderedConfig.Replace('__MODEL_CATALOG_JSON__', (& $tomlEscape $catalog))
$renderedConfig = $renderedConfig.Replace('__CODEX_HOME__', (& $tomlEscape $codexHome))
$renderedConfig | Set-Content -LiteralPath (Join-Path $codexHome 'config.toml') -Encoding utf8

$savedCodexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
$exitCode = 1
try {
    $env:CODEX_HOME = $codexHome
    Write-Host "Starting Codex with $ModelId ($($model.ollama_model))"
    Write-Host "Workspace: $([System.IO.Path]::GetFullPath($WorkingDirectory))"
    & codex -C $WorkingDirectory -m $model.ollama_model
    $exitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $savedCodexHome, 'Process')
}

exit $exitCode
