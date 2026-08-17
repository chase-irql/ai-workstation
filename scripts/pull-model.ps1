[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$ModelId)

. (Join-Path $PSScriptRoot 'common.ps1')
$model = Get-ModelDefinition -ModelId $ModelId
$expectedStore = [System.IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) 'models\ollama'))
$configuredStore = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
if (-not $configuredStore -or [System.IO.Path]::GetFullPath($configuredStore) -ne $expectedStore) {
    throw "OLLAMA_MODELS is not configured for $expectedStore. Run configure-ollama.ps1 first."
}

$drive = Get-PSDrive -Name D
$requiredBytes = [double]$model.download_gb * 1GB * 1.15
if ($drive.Free -lt $requiredBytes) {
    throw "Insufficient free space for $($model.ollama_model) plus download headroom."
}

Write-Host "Pulling $($model.ollama_model) to $expectedStore"
& ollama pull $model.ollama_model
if ($LASTEXITCODE -ne 0) { throw "ollama pull failed with exit code $LASTEXITCODE" }
& ollama show $model.ollama_model

