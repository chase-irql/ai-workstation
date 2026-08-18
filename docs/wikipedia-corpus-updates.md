# Wikipedia corpus updates

Wikipedia updates are built as new, date-versioned generations. The serving database is never edited in place, so the current search service remains available until the replacement has passed verification.

## Update sequence

Replace the example date with a published Wikimedia dump date:

```powershell
.\scripts\download-wikipedia.ps1 -DumpDate 20260901
.\scripts\run-wikipedia-full.ps1 -DumpDate 20260901
.\scripts\plan-wikipedia-update.ps1 -PreviousDumpDate 20260801 -DumpDate 20260901
.\scripts\run-wikipedia-semantic-full.ps1 `
    -DumpDate 20260901 `
    -ReuseFromDumpDate 20260801 `
    -Background
.\scripts\get-wikipedia-semantic-status.ps1 -DumpDate 20260901
```

The planner is CPU-only. It streams both BM25 databases in stable document-ID order and hashes the exact title-plus-lead representation that would be sent to the embedding model. It reports unchanged, modified, added, and deleted searchable documents plus the number of embeddings expected to be reused or generated.

The semantic update verifies the previous generation by default. `-SkipReuseChecksums` avoids rehashing the previous FAISS and metadata files, but should be used only when that generation has already been independently verified and has remained read-only.

If an update is interrupted, pass the identical previous generation and execution settings when resuming:

```powershell
.\scripts\run-wikipedia-semantic-full.ps1 `
    -DumpDate 20260901 `
    -ReuseFromDumpDate 20260801 `
    -Resume `
    -Background
```

## Reuse rules

A vector is reused only when all of these match:

- stable document ID;
- exact embedding-input SHA-256;
- embedding provider/model identity;
- vector dimensions;
- representation settings (`max_chunks` and `max_characters`).

Fresh citation metadata always comes from the new BM25 database. A reused vector therefore does not preserve an obsolete title, URL, revision timestamp, or source version.

New semantic metadata stores the exact embedding-input fingerprint and the prior generation/vector ID when reuse occurs. The already-running version-1 Wikipedia generation has no fingerprint table, but remains safely reusable with its production `max_chunks=1` representation because the exact prior input can be reconstructed from its stored title and lead text. Reuse from a legacy generation with multiple embedded chunks is rejected rather than guessed.

The update build uses the same durable raw-vector and transactional SQLite checkpoint as a full build. Resume validates both the new source identity and the reuse-generation identity. Reuse and newly generated counts are recovered from committed per-vector provenance instead of trusting possibly stale progress counters.

## What still rebuilds

The raw dump is a complete Wikimedia snapshot, so extraction and the SQLite FTS5/BM25 database are currently rebuilt in new date-specific paths. The semantic stage is incremental: it copies unchanged vectors and calls the embedding model only for new or modified representations. FAISS is assembled again from the completed vector matrix; this is much cheaper than regenerating millions of embeddings.

An incremental SQLite updater is intentionally not implemented yet. A full side-by-side BM25 build has simpler deletion, redirect, FTS, and rollback semantics. It should be optimized only after measured update timing shows that it is the dominant cost.

## Cutover and rollback

After the new extraction, BM25 index, semantic index, evaluation, and tests succeed:

```powershell
.\scripts\stop-wikipedia-service.ps1
.\scripts\start-wikipedia-service.ps1 -DumpDate 20260901 -Background
.\scripts\configure-wikipedia-mcp.ps1 -DumpDate 20260901 -Force
```

Retain the preceding raw dump and both index generations until the new service has been exercised. Rollback consists of restarting the service and MCP configuration with the preceding dump date. Generated indexes may be removed later because they are reproducible; source dumps, manifests, and curated data deserve backup priority.
