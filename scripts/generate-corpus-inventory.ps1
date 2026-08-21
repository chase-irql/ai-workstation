[CmdletBinding()]
param([string]$Output = 'docs\knowledge-ark-corpus-list.md')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$registry = Get-Content -LiteralPath (Join-Path $root 'config\datasets.json') -Raw | ConvertFrom-Json
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $root $Output))

function Escape-MarkdownCell([object]$Value) {
    if ($null -eq $Value) { return '' }
    return ([string]$Value).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ').Trim()
}

function Get-LocalState($Dataset) {
    $index = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$Dataset.paths.index)))
    $raw = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$Dataset.paths.raw)))
    $processed = [System.IO.Path]::GetFullPath((Join-Path $root ([string]$Dataset.paths.processed)))
    $semantic = if ($Dataset.paths.PSObject.Properties.Name -contains 'semantic_index') {
        [System.IO.Path]::GetFullPath((Join-Path $root ([string]$Dataset.paths.semantic_index)))
    } else { $null }
    if (Test-Path -LiteralPath $index -PathType Leaf) {
        if ($semantic -and (Test-Path -LiteralPath (Join-Path $semantic 'manifest.json') -PathType Leaf)) {
            return 'Indexed + semantic search'
        }
        return 'Indexed (BM25)'
    }
    if (Test-Path -LiteralPath (Join-Path $processed 'corpus-manifest.json') -PathType Leaf) { return 'Parsed; index pending' }
    if (Test-Path -LiteralPath (Join-Path $raw 'acquisition-manifest.json') -PathType Leaf) { return 'Downloaded; processing pending' }
    return 'Registered / queued'
}

$items = foreach ($dataset in $registry.datasets) {
    [pscustomobject]@{
        Category = [string]$dataset.category
        Name = [string]$dataset.name
        Id = [string]$dataset.dataset_id
        Description = [string]$dataset.description
        Release = [string]$dataset.release
        License = [string]$dataset.license
        State = Get-LocalState $dataset
    }
}
$indexed = @($items | Where-Object State -Like 'Indexed*').Count
$semantic = @($items | Where-Object State -eq 'Indexed + semantic search').Count
$pending = $items.Count - $indexed

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('# Offline AI Knowledge Ark — Corpus List')
$lines.Add('')
$lines.Add('This is the shareable inventory of the local, offline knowledge system. It lists what the system can search; it does **not** include or redistribute the corpus files themselves.')
$lines.Add('')
$lines.Add("Updated: $((Get-Date).ToString('yyyy-MM-dd'))")
$lines.Add('')
$lines.Add('## At a glance')
$lines.Add('')
$totalFamilies = $items.Count + 1
$lines.Add("- **$totalFamilies total corpus families**: English Wikipedia plus $($items.Count) registry-managed datasets.")
$lines.Add("- **$indexed registry datasets indexed locally**; **$semantic** currently also have semantic/vector retrieval.")
$pendingVerb = if ($pending -eq 1) { 'is' } else { 'are' }
$lines.Add("- **$pending registry $(if ($pending -eq 1) { 'dataset' } else { 'datasets' }) $pendingVerb registered, downloading, or being processed.**")
$lines.Add('- Retrieval uses SQLite FTS5/BM25 as the durable baseline, with per-corpus semantic/hybrid search where embeddings are available.')
$lines.Add('- Every registry entry records its official source, pinned release/snapshot, license or usage terms, local paths, and update notes.')
$lines.Add('- Source archives, processed text, indexes, vectors, books, manuals, and other large datasets stay outside the public Git repository.')
$lines.Add('')
$lines.Add('## Wikipedia')
$lines.Add('')
$lines.Add('| Corpus | Coverage | Local state |')
$lines.Add('|---|---|---|')
$lines.Add('| English Wikipedia (`enwiki-20260801`) | 7,215,325 searchable articles and roughly 35.8 million chunks | Indexed with BM25 plus article-level semantic/hybrid search |')

foreach ($group in ($items | Sort-Object Category, Name | Group-Object Category)) {
    $heading = (($group.Name -split '-') | ForEach-Object {
        if ($_ -in @('api', 'ui')) { $_.ToUpperInvariant() } else { (Get-Culture).TextInfo.ToTitleCase($_) }
    }) -join ' '
    $lines.Add('')
    $lines.Add("## $heading")
    $lines.Add('')
    $lines.Add('| Corpus | What it covers | Pinned version / snapshot | Local state |')
    $lines.Add('|---|---|---|---|')
    foreach ($item in ($group.Group | Sort-Object Name)) {
        $escapedName = Escape-MarkdownCell $item.Name
        $escapedId = Escape-MarkdownCell $item.Id
        $name = '{0} (`{1}`)' -f $escapedName, $escapedId
        $lines.Add("| $name | $(Escape-MarkdownCell $item.Description) | $(Escape-MarkdownCell $item.Release) | $(Escape-MarkdownCell $item.State) |")
    }
}

$lines.Add('')
$lines.Add('## Licensing and reproducibility')
$lines.Add('')
$lines.Add('The collection mixes open licenses, government works, attribution/share-alike material, and private-reference-only documentation. Each dataset keeps its own terms and provenance. The public project should distribute the code, manifests, importers, tests, and reproducible acquisition instructions—not copyrighted corpus payloads.')
$lines.Add('')
$lines.Add('The machine-readable source of truth is [`config/datasets.json`](../config/datasets.json). Wikipedia uses a separate manifest because its multistream dump and update process are specialized.')

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
[System.IO.File]::WriteAllLines($outputPath, $lines, [System.Text.UTF8Encoding]::new($false))
Write-Output $outputPath
