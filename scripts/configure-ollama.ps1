[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TargetStore,
    [ValidateRange(4096, 1048576)][int]$ContextLength = 65536,
    [switch]$MigrateExistingStore,
    [switch]$AllowExternalStore,
    [switch]$RestartApp
)

. (Join-Path $PSScriptRoot 'common.ps1')

$root = Get-ProjectRoot
if (-not $TargetStore) { $TargetStore = Join-Path $root 'models\ollama' }
$target = [System.IO.Path]::GetFullPath($TargetStore)
$rootPrefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $AllowExternalStore -and -not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Target store must remain under the project root unless -AllowExternalStore is supplied. Resolved path: $target"
}
New-Item -ItemType Directory -Force -Path $target | Out-Null

$names = @('OLLAMA_MODELS','OLLAMA_CONTEXT_LENGTH','OLLAMA_FLASH_ATTENTION','OLLAMA_KV_CACHE_TYPE','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS')
$before = [ordered]@{}
foreach ($name in $names) { $before[$name] = [Environment]::GetEnvironmentVariable($name, 'User') }

if ($MigrateExistingStore) {
    $source = Join-Path $env:USERPROFILE '.ollama\models'
    if ((Test-Path -LiteralPath $source) -and ([System.IO.Path]::GetFullPath($source) -ne $target)) {
        if ($PSCmdlet.ShouldProcess($target, "Copy existing Ollama model store from $source")) {
            Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
            }
        }
    }
}

$settings = [ordered]@{
    OLLAMA_MODELS = $target
    OLLAMA_CONTEXT_LENGTH = $ContextLength.ToString()
    OLLAMA_FLASH_ATTENTION = '1'
    OLLAMA_KV_CACHE_TYPE = 'q8_0'
    OLLAMA_NUM_PARALLEL = '1'
    OLLAMA_MAX_LOADED_MODELS = '1'
}

foreach ($entry in $settings.GetEnumerator()) {
    if ($PSCmdlet.ShouldProcess("User environment", "Set $($entry.Key)=$($entry.Value)")) {
        [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'User')
        Set-Item -Path "Env:$($entry.Key)" -Value ([string]$entry.Value)
    }
}

$snapshot = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    before = $before
    after = $settings
    source_store_retained = (Join-Path $env:USERPROFILE '.ollama\models')
}
$snapshotPath = Join-Path $root 'results\ollama-environment-snapshot.json'
$snapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $snapshotPath -Encoding UTF8

if ($RestartApp) {
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "Ollama executable not found at $exe" }
    if ($PSCmdlet.ShouldProcess('Ollama app', 'Restart to apply environment settings')) {
        Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'ollama*' } | Stop-Process -Force
        Start-Sleep -Milliseconds 750
        Start-Process -FilePath $exe -ArgumentList 'app' -WindowStyle Hidden
        $ready = $false
        foreach ($attempt in 1..30) {
            Start-Sleep -Milliseconds 500
            try {
                Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            } catch { }
        }
        if (-not $ready) { throw 'Ollama did not become ready after restart.' }
    }
}

Write-Host "Ollama store: $target"
Write-Host "Context: $ContextLength; Flash Attention: 1; KV cache: q8_0; Parallel: 1; Loaded models: 1"
Write-Host "Previous model store was retained; no source data was deleted."
