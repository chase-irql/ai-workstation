# iFixit ingestion

The iFixit adapter indexes the complete English Kiwix snapshot as structured repair procedures while retaining the original ZIM as the offline media archive. It does not duplicate image binaries into JSONL or SQLite.

## Source and license

The registered source is the versioned `ifixit_en_all_2025-12.zim` produced by Kiwix/openZIM. iFixit explicitly supports offline use and documents both its API and offline archives. iFixit content and API data are CC BY-NC-SA 3.0: attribution and source links must be retained, commercial use is prohibited without a separate license, adaptations are share-alike, and iFixit prohibits using the material to train language models. Retrieval over an offline archive is not model training, but the raw corpus and generated index must not be published in this repository.

The dataset registry pins the publisher SHA-256 and exact byte range. Acquisition is resumable, validates the publisher digest, and publishes the final filename only after validation.

The published 2025-12 generation contains 55,345 guides and 1,773 teardowns represented by 643,871 chunks. Its 25-case stable-ID lexical gate achieves `1.0` at every Success, MRR, Recall, and nDCG cutoff, with 10.066 ms mean query latency on the development workstation. A separate 20-case paraphrase suite records hybrid Success@10 `0.75` and Recall@50 `0.9`; deterministic reranking raises Success@1 from `0.4` to `0.55`. These results justify conceptual hybrid routing but also preserve five known top-10 misses for future tuning.

## One-command pipeline

From the repository root:

```powershell
.\scripts\run-ifixit-pipeline.ps1
```

If the archive is absent, the script acquires it first. It then:

1. verifies the ZIM internal checksum;
2. reads Guide and Teardown entries without extracting the media tree;
3. writes atomic common-record `documents.jsonl` and `chunks.jsonl` files;
4. builds and validates the SQLite FTS5/BM25 database;
5. leaves an existing processed corpus or index untouched unless `-Force` is explicit.

For a small, disposable validation run, use temporary output paths with the Python module directly, or temporarily register a separate pilot dataset. Do not use `-Force` against the production paths merely to create a pilot.

## Quality and semantic publication

After a new version completes its atomic BM25 build, run the exact-title and paraphrase gates separately:

```powershell
.\scripts\evaluate-documentation.ps1 `
  -DatasetId ifixit-english-2025-12 `
  -Suite rag\eval\ifixit-english-2025-12-v1.json

.\scripts\run-corpus-semantic.ps1 `
  -DatasetId ifixit-english-2025-12 `
  -BatchSize 128 `
  -EmbeddingWorkers 2 `
  -Unload

.\scripts\evaluate-corpus-semantic.ps1 `
  -DatasetId ifixit-english-2025-12 `
  -Suite rag\eval\ifixit-english-2025-12-semantic-v1.json `
  -Mode all `
  -Unload
```

The semantic generation is resumable with `-Resume`. Do not mark a new snapshot evaluated or add it to the MCP configuration until the vector manifest verifies against the exact BM25 build and both reports have been inspected. Then run `configure-knowledge-mcp.ps1 -Harness opencode -Force` and start a new OpenCode session.

## Record structure

One iFixit guide or teardown becomes one common document. Its attributes retain:

- guide ID and type;
- category/device context;
- summary, difficulty, and estimated time;
- publication and modification timestamps;
- tools and parts;
- original ZIM entry path;
- exact canonical iFixit source URL;
- CC BY-NC-SA 3.0 license identifier.

Each guide produces an overview chunk followed by one or more chunks per ordered procedure step. Step chunks retain:

- step number and title;
- bullet nesting;
- visible warning-marker color;
- a safety-sensitive flag;
- ordered neighboring chunk IDs;
- image URLs and alt text as metadata.

This prevents unrelated steps from being merged into a generic page chunk and makes exact procedural citations possible. Images stay available inside the raw ZIM for offline browsing and future vision retrieval.

## Updates

Treat each Kiwix snapshot as an immutable corpus version.

1. Inspect the official Kiwix iFixit directory for a newer complete English snapshot.
2. Record its release date, exact `Content-Length`, and adjacent publisher SHA-256.
3. Add a new versioned dataset entry and new raw, processed, index, and semantic-index paths.
4. Acquire and validate the new ZIM without changing the active version.
5. Import, index, and run the stable-ID evaluation suite.
6. Configure the MCP to use the new dataset only after the quality gate passes.
7. Retain the previous snapshot until the new service configuration and citations are verified.

Never overwrite an old ZIM in place. Generated JSONL and SQLite files are reproducible; the publisher archive and acquisition manifest are the preservation assets.

## Storage model

- Raw ZIM: complete offline content and compressed media.
- Processed JSONL: normalized text and provenance only.
- SQLite FTS5: active lexical index on NVMe.
- Future semantic index: optional and versioned separately.

The raw ZIM should move to bulk HDD storage when available, while the SQLite index remains on NVMe. The registered path can later be replaced by a junction or another explicitly documented storage mapping without changing record IDs.
