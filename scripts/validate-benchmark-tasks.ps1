[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$validationRoot = Join-Path $root 'runtime\task-validation'
New-Item -ItemType Directory -Force -Path $validationRoot | Out-Null

$tasks = Get-ChildItem -LiteralPath (Join-Path $root 'benchmarks\tasks') -Filter '*.json' |
    Sort-Object Name |
    ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json }

foreach ($task in $tasks) {
    $seed = [System.IO.Path]::GetFullPath((Join-Path $root $task.seed_repository))
    if (-not (Test-Path -LiteralPath $seed)) { throw "Missing seed for $($task.id): $seed" }

    $referencePatch = Join-Path $root "benchmarks\reference-solutions\$($task.id).patch"
    if (-not (Test-Path -LiteralPath $referencePatch)) {
        Write-Output "SKIP $($task.id): no reference patch"
        continue
    }

    $workspace = Join-Path $validationRoot $task.id
    if (Test-Path -LiteralPath $workspace) {
        $resolved = [System.IO.Path]::GetFullPath($workspace)
        if (-not $resolved.StartsWith([System.IO.Path]::GetFullPath($validationRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clear unexpected validation path: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $workspace | Out-Null
    Copy-Item -Path (Join-Path $seed '*') -Destination $workspace -Recurse -Force

    & git -C $workspace init --quiet
    & git -C $workspace apply --check $referencePatch
    if ($LASTEXITCODE -ne 0) { throw "Reference patch does not apply for $($task.id)" }
    & git -C $workspace apply $referencePatch
    if ($LASTEXITCODE -ne 0) { throw "Reference patch failed for $($task.id)" }

    Push-Location $workspace
    try {
        & $task.verify.command @($task.verify.args)
        if ($LASTEXITCODE -ne 0) { throw "Reference solution failed verification for $($task.id)" }
    } finally {
        Pop-Location
    }
    Write-Output "PASS $($task.id)"
}
