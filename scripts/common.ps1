Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'

function Get-ProjectRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-ModelRegistry {
    $path = Join-Path (Get-ProjectRoot) 'config\models.json'
    return (Get-Content -Raw -LiteralPath $path | ConvertFrom-Json)
}

function Get-ModelDefinition {
    param([Parameter(Mandatory = $true)][string]$ModelId)
    $registry = Get-ModelRegistry
    $model = @($registry.models | Where-Object { $_.id -eq $ModelId })
    if ($model.Count -ne 1) {
        throw "Unknown or duplicate model id '$ModelId'."
    }
    return $model[0]
}

function Get-CommandVersion {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { return $null }
    return ((& $Name --version 2>&1 | Select-Object -First 1) -join '').Trim()
}

function Get-GpuSnapshot {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { return $null }
    $line = (& nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,power.draw --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if (-not $line) { return $null }
    $parts = $line -split ',\s*'
    return [ordered]@{
        name = $parts[0]
        driver = $parts[1]
        memory_total_mib = [int]$parts[2]
        memory_used_mib = [int]$parts[3]
        memory_free_mib = [int]$parts[4]
        utilization_percent = [int]$parts[5]
        power_watts = [double]$parts[6]
    }
}

function Get-OllamaRunningModels {
    try {
        return Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:11434/api/ps' -TimeoutSec 5
    } catch {
        return $null
    }
}
