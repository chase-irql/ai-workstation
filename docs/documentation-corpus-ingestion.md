# Documentation corpus ingestion

The documentation pipeline is the first corpus-neutral path beside Wikipedia. It keeps acquisition, parsing, indexing, and evaluation separate so a failed update cannot replace a working corpus or database.

## Current pilots

Python 3.14.7 is the first completed dataset:

- source archive: `corpora/raw/documentation/python-3.14/python-3.14-docs-html.zip`;
- validated extraction: `corpora/raw/documentation/python-3.14/extracted/`;
- common records: `corpora/processed/documentation/python-3.14/`;
- BM25 index: `indexes/documentation/python-3.14.sqlite3`;
- 565 documents and 8,840 chunks;
- local archive SHA-256: `9306da398ae5a9142deb22d5c7865994fe0ada961022c8dea8ee341348e14181`.

The official archive listing did not publish a checksum, so the acquisition manifest explicitly records `publisher_checksum_verified: false`. ZIP structure and CRCs were validated and the local SHA-256 makes the acquired artifact reproducible.

The five-query lexical pilot achieved Success@1/5/10, MRR@10, and Recall@5/10/50 of 1.0. nDCG@10 was 0.922776. The suite is intentionally small; it proves the ingestion and retrieval path, not broad retrieval quality.

Git 2.55.0 and Linux man-pages 6.18 are also acquired, publisher-checksum verified, parsed, indexed, and evaluated:

- Git: 985 documents, 4,953 chunks, Success@1 and MRR@10 of 1.0, nDCG@10 of 0.882939;
- Linux man-pages: 1,245 documents, 13,155 chunks, Success@1, MRR@10, and nDCG@10 of 1.0.

The RFC Editor text snapshot dated 2026-08-19 is also complete:

- 10,057 regular source files and 555,449,714 bytes acquired from the official `rfcs-text-only` rsync module;
- every regular file recorded in a SHA-256 inventory whose aggregate hash is `8d575f0b1785b6c5ac710f48ce7c4ee129e9d79d81f7e7686726f2a23f4d3ac2`;
- 292 BCP/FYI/STD symlink aliases intentionally omitted because the target RFC text is already present;
- 9,822 primary RFC publications parsed into 348,831 chunks and a 9,822-document SQLite index;
- RFC number, publication date/status, ISSN, `obsoletes`, and `updates` metadata preserved where present;
- six-query gate: Success@1/5/10 and MRR@10 of 1.0, Recall@10/50 of 1.0, and nDCG@10 of 0.903258.

The IANA assignments snapshot dated 2026-08-19 is complete through its corpus-specific structured importer:

- 8,269 official assignment files and 70,672,402 bytes acquired through IANA's rsync service;
- every regular file recorded in a SHA-256 inventory with aggregate hash `7c8e859136528cfe12aab4840f837ede1d8054541c50a7126cdcb8c05257b462`;
- 675 registry XML files parsed into 4,256 nested registry documents, 110,423 table records, and 114,590 chunks;
- field names, nested registry hierarchy, references, timestamps, XML source paths, XHTML citation fragments, and CC0 provenance preserved;
- six-query exact technical gate: Success@1/5/10, MRR@10, Recall@5/10/50, and nDCG@10 of 1.0.

SQLite 3.53.4 documentation is complete through the generic HTML documentation path with SQLite-specific parser coverage:

- official 11,820,412-byte static documentation ZIP acquired over HTTPS;
- publisher SHA3-256 `7ccf86a52e7dd1fb9b31e63edcebe3b553f18f89cd26eef59c7f191a5111836e` verified against SQLite's download page;
- local archive SHA-256 `a1d0f5de57485d062796ed7e67daff0758b50d00001a0f233a2c15aaf40bbdc8` recorded for reproducibility;
- 837 HTML source files inspected, producing 765 documents and 4,384 chunks; 72 navigation/index-only pages were empty after filtering and intentionally skipped;
- optional HTML end tags used by the generated SQLite pages are handled without merging neighboring paragraphs, lists, or code blocks;
- 20-query lexical gate: Success@1 0.95, Success@5/10 and Recall@5/10/50 1.0, MRR@10 0.975, and nDCG@10 0.966274.
- all 4,384 chunks have a source-verified 256-dimensional Qwen3-Embedding generation; on 12 paraphrase cases, warm hybrid retrieval achieved Success@10 0.916667 and Recall@50 1.0, while deterministic reranking raised Success@5 from 0.833333 to 0.916667.

The raw Unix archives contain safe internal symbolic links, NTFS-invalid colons, and case-distinct names. Extraction validates that links cannot escape but does not duplicate their targets. NTFS-invalid characters and uppercase ASCII are reversibly percent-encoded on disk, with a versioned marker; the importer decodes the original Unix paths before producing IDs, provenance, and version-pinned kernel.org citations.

## Data stages

`config/datasets.json` is the versioned acquisition plan. Generated `acquisition-manifest.json`, `corpus-manifest.json`, SQLite metadata, and evaluation reports are the evidence for a particular run.

The status vocabulary is:

1. `planned`: source, scope, license, paths, and conservative storage bounds recorded.
2. `downloaded`: transfer completed atomically.
3. `validated`: size and checksum/format validation passed.
4. `extracted`: archive members were safely published and validated.
5. `parsed`: corpus-neutral document and chunk records were published.
6. `indexed`: the temporary SQLite build passed referential/count/smoke validation and was atomically published.
7. `evaluated`: a versioned retrieval suite was run against that index.

The registry is a human-reviewed current-state summary, not a substitute for the generated manifests.

## Acquire, import, index, and query

Validate the plan first:

```powershell
.\scripts\validate-dataset-registry.ps1
```

The HTTP acquisition wrapper supports resume through `.partial` files, retries with backoff, a free-space reserve, expected-size bounds, optional publisher SHA-256 or SHA3-256 verification, local SHA-256 calculation, safe ZIP/tar extraction, and atomic publication:

```powershell
.\scripts\acquire-dataset.ps1 -DatasetId python-3.14-docs -Extract
```

SQLite uses the same command with its publisher-supplied SHA3-256 and version-pinned static HTML archive:

```powershell
.\scripts\acquire-dataset.ps1 -DatasetId sqlite-docs -Extract
.\scripts\run-documentation-pilot.ps1 `
  -DatasetId sqlite-docs `
  -SourceRoot .\corpora\raw\documentation\sqlite\extracted\sqlite-doc-3530400
.\scripts\evaluate-documentation.ps1 `
  -DatasetId sqlite-docs `
  -Suite rag\eval\sqlite-docs-v1.json
```

Versioned rsync snapshots use WSL rsync, resolve the official host before transfer, retain resumable partials, omit alias symlinks, hash every regular file, and publish only after inventory validation:

```powershell
.\scripts\acquire-rsync-dataset.ps1 -DatasetId rfc-editor-text
.\scripts\acquire-rsync-dataset.ps1 -DatasetId iana-protocol-registries -Snapshot 2026-08-19
```

Import and atomically index the verified IANA snapshot with its table-aware path:

```powershell
.\scripts\run-iana-pipeline.ps1
.\scripts\query-documentation.ps1 -DatasetId iana-protocol-registries -Query 'https tcp port'
.\scripts\evaluate-documentation.ps1 -DatasetId iana-protocol-registries -Suite rag\eval\iana-registries-v1.json
```

Import and index a registered source tree:

```powershell
.\scripts\run-documentation-pilot.ps1 `
  -DatasetId python-3.14-docs `
  -SourceRoot D:\ai-workstation\corpora\raw\documentation\python-3.14\extracted
```

Existing processed output and indexes are protected. Use `-Force` only for a deliberate rebuild. The importer replaces only a recognized importer output directory, and the indexer builds beside the target before an authorized atomic replacement.

Query or evaluate without loading an LLM or using the GPU:

```powershell
.\scripts\query-documentation.ps1 `
  -DatasetId python-3.14-docs `
  -Query 'asyncio TaskGroup cancellation'

.\scripts\evaluate-documentation.ps1 `
  -DatasetId python-3.14-docs `
  -Suite rag\eval\python-docs-pilot-v1.json

.\scripts\query-documentation.ps1 `
  -DatasetId rfc-editor-text `
  -Query 'QUIC transport connection migration'
```

## Record and parser behavior

The importer emits the common records described in `docs/rag-record-schema.md`. Stable document IDs derive from corpus ID and relative source path. A `content_id` derives from normalized chunk text for deduplication and future embedding reuse; a separate chunk-instance ID identifies that occurrence in a document version. Neighbor IDs, heading paths, source paths, formats, source hashes, source version, URL, timestamp, and license are retained.

Supported inputs are:

- HTML (including compound generated suffixes such as Apache's `.html.en`), with navigation, search, sidebar, generated-index, script, and static boilerplate filtered;
- Markdown (including YAML front matter), reStructuredText, and AsciiDoc, including code fences/directives;
- DocBook XML with section/option/list/table/code structure, network-disabled DTD handling, and same-directory ID-based XInclude resolution;
- roff/man pages with section hierarchy;
- Perl POD and generated POD.IN command/API manuals;
- RFC text with titles, numbered/appendix/common section hierarchy, conservative page-furniture filtering, and publication metadata;
- plain text as a safe fallback.

Chunks respect structural boundaries where possible. Oversized blocks split deterministically, and short trailing chunks merge when doing so stays within the configured ceiling.

DocBook build-time entities that cannot be resolved without a project build are retained as deterministic searchable names. Shared include fragments should be excluded as standalone inputs after being incorporated into their published manuals; includes never resolve outside the source file's directory or across the network.

## Updating a documentation dataset

Updates are side-by-side operations conceptually, even if the stable registry path is reused during the final local cutover:

1. Resolve and record the exact upstream release and license.
2. Update the registry release, URL, and expected storage bounds in reviewable source control.
3. Acquire and validate the new archive without deleting the prior archive.
4. Import to a staging path or a version-specific path.
5. Build a temporary index and run its structural validation.
6. Run the stable evaluation suite and add cases for new features or known failures.
7. Compare both evaluation reports and manually inspect citations.
8. Atomically publish the new processed generation/index only after acceptance.
9. Keep the prior generation until rollback is no longer required.

Stable IDs survive a version update when relative source paths remain stable. Chunk instance IDs intentionally change when version, heading, ordinal, or text changes. Unchanged `content_id` values can later reuse cached embeddings.

## Current limitations and next stages

Resumable HTTPS archives and versioned rsync snapshots are automated. Git clones and sites requiring a resolved export URL still require a corpus-specific acquisition adapter or a reviewed manual acquisition. The registry refuses to pretend those are ordinary HTTP downloads.

IANA registries use `offline_rag.iana`, and Stack Exchange XML uses `offline_rag.stack_exchange`; neither is flattened through the generic documentation importer. PDFs, JATS, maps, packages, and disk images likewise need their own handlers.

Documentation, IANA, and DevOps Stack Exchange are exposed through the unified knowledge MCP without merging their databases. The corpus-neutral chunk-level semantic builder is active for Python, Git, man-pages, RFCs, SQLite, and DevOps Stack Exchange; IANA remains exact BM25/structured-first. The rollout results, routing rules, and activation gates are documented in `docs/corpus-semantic-roadmap.md`.
