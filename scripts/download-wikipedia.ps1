[CmdletBinding()]
param(
    [ValidatePattern('^\d{8}$')][string]$DumpDate = '20260801'
)

. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-ProjectRoot
$destinationRoot = Join-Path $root "corpora\raw\wikipedia\enwiki-$DumpDate"
$runtimeRoot = Join-Path $root 'runtime\wikipedia-download'
$statePath = Join-Path $runtimeRoot "enwiki-$DumpDate-state.json"
$baseUri = "https://dumps.wikimedia.org/enwiki/$DumpDate"
$prefix = "enwiki-$DumpDate"
$archiveName = "$prefix-pages-articles-multistream.xml.bz2"
$indexName = "$prefix-pages-articles-multistream-index.txt.bz2"
$checksumName = "$prefix-sha1sums.txt"
$jobName = "Local AI Wikipedia enwiki-$DumpDate"

New-Item -ItemType Directory -Force -Path $destinationRoot, $runtimeRoot | Out-Null

function Write-DownloadState {
    param([string]$Status, [string]$Message = '')
    [ordered]@{
        schema_version = 1
        dump = "enwiki-$DumpDate"
        status = $Status
        message = $Message
        updated_at = (Get-Date).ToString('o')
        destination = $destinationRoot
        files = @($archiveName, $indexName, $checksumName)
        expected_download_bytes = 26952317546
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

try {
    Write-DownloadState -Status 'starting'
    $checksumPath = Join-Path $destinationRoot $checksumName
    Invoke-WebRequest -Uri "$baseUri/$checksumName" -OutFile $checksumPath -TimeoutSec 120

    $sources = @("$baseUri/$archiveName", "$baseUri/$indexName")
    $destinations = @((Join-Path $destinationRoot $archiveName), (Join-Path $destinationRoot $indexName))
    Write-DownloadState -Status 'downloading'
    Start-BitsTransfer -Source $sources -Destination $destinations -DisplayName $jobName `
        -Description 'English Wikipedia articles-only multistream dump for the local RAG system' `
        -TransferType Download -Priority Foreground

    Write-DownloadState -Status 'verifying'
    $checksums = Get-Content -LiteralPath $checksumPath
    $verified = @()
    foreach ($name in @($archiveName, $indexName)) {
        $line = $checksums | Where-Object { $_ -match "^[0-9a-fA-F]{40}\s+\*?$([regex]::Escape($name))$" } | Select-Object -First 1
        if (-not $line) { throw "No SHA1 entry found for $name" }
        $expected = ($line -split '\s+')[0].ToUpperInvariant()
        $actual = (Get-FileHash -LiteralPath (Join-Path $destinationRoot $name) -Algorithm SHA1).Hash
        if ($actual -ne $expected) { throw "SHA1 mismatch for $name" }
        $verified += [ordered]@{ file = $name; sha1 = $actual; bytes = (Get-Item -LiteralPath (Join-Path $destinationRoot $name)).Length }
    }

    $manifest = [ordered]@{
        schema_version = 1
        dump = "enwiki-$DumpDate"
        source = "$baseUri/"
        completed_at = (Get-Date).ToString('o')
        files = $verified
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destinationRoot 'manifest.json') -Encoding UTF8
    Write-DownloadState -Status 'complete' -Message 'Download and SHA1 verification succeeded.'
} catch {
    Write-DownloadState -Status 'failed' -Message $_.Exception.Message
    throw
}
