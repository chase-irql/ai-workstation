# Stack Exchange corpus ingestion

The Stack Exchange adapter preserves the site dump's question-and-answer structure while emitting the same common document and chunk records used by the rest of the retrieval system. DevOps Stack Exchange is the pilot because it is technically valuable and small enough to validate the complete lifecycle before attempting Stack Overflow.

## Pinned pilot

- Dataset ID: `devops-stackexchange`.
- Release: coordinated community dump through June 30, 2026.
- Archive size: 18,189,978 bytes.
- Publisher/coordinated SHA-256: `a08a86c7c386c0f0798817e64ecde03368908c7ed1cf90d2259f8f209421114b`.
- Extracted archive: 10 XML files, 92,821,208 bytes.
- Imported: 5,589 questions, 2,509 accepted answers, and 3,779 other positively scored answers.
- Published: 11,877 post documents and 13,531 chunks.

Downloaded dumps and generated records are intentionally excluded from Git. The registry, importer, tests, evaluation suites, and this reproducible procedure are distributed.

## Retention and identity

The importer keeps every question, every accepted answer even when its score is zero or negative, and every other answer with a positive score. Zero- and negative-score non-accepted answers are excluded. Deleted or synthetic administrative rows documented by the dump format are not treated as content.

Each retained post is its own common document. A question uses `https://devops.stackexchange.com/questions/{id}` and an answer uses `https://devops.stackexchange.com/a/{id}`, so citations point to the exact contribution. Answer attributes retain the parent question ID and title. Stable IDs use `devops-stackexchange:post:{id}`.

The adapter also preserves tags, post score, accepted status, view and answer counts for questions, creation/edit/activity dates, contributor ID and display name when available, and each post's exact `ContentLicense`. Rendered HTML is converted into structured text without discarding headings, lists, or code blocks.

## Build from scratch

Install the pinned Python dependencies, including `py7zr`, then run:

```powershell
.\scripts\validate-dataset-registry.ps1
.\scripts\acquire-dataset.ps1 -DatasetId devops-stackexchange -Extract
.\scripts\run-stack-exchange-pipeline.ps1
.\scripts\evaluate-documentation.ps1 `
  -DatasetId devops-stackexchange `
  -Suite rag\eval\devops-stackexchange-v1.json
```

Acquisition is resumable, verifies the registered SHA-256, validates 7z member paths and sizes, and atomically publishes extraction. Import and SQLite construction likewise build beside the destination and require `-Force` before replacing recognized output.

Build the evaluated high-fidelity semantic profile with model ID `qwen3-embedding-0.6b-1024`. The current development generation lives at `indexes/semantic/devops-stackexchange-1024`; the ordinary corpus semantic script reads that location from `config/datasets.json`:

```powershell
.\scripts\run-corpus-semantic.ps1 `
  -DatasetId devops-stackexchange `
  -ModelId qwen3-embedding-0.6b-1024 `
  -EmbeddingWorkers 2 `
  -Unload

.\scripts\evaluate-corpus-semantic.ps1 `
  -DatasetId devops-stackexchange `
  -Suite rag\eval\devops-stackexchange-semantic-v1.json `
  -ModelId qwen3-embedding-0.6b-1024 `
  -Mode all `
  -Unload
```

## Query

CPU-only search requires no model:

```powershell
.\scripts\query-documentation.ps1 `
  -DatasetId devops-stackexchange `
  -Query 'Terraform remote state locking'
```

Through MCP, filter `search_knowledge` to `corpora=["devops-stackexchange"]`. Prefer `retrieval="bm25"` for error strings, product names, commands, and exact technical terms. `retrieval="hybrid"` can help broader natural-language questions, but the checked-in paraphrase suite records its current limitations.

## Update procedure

1. Identify a newer coordinated site archive and independently confirmed SHA-256.
2. Add the new release, URL, checksum, and realistic size bounds to a reviewed registry change.
3. Acquire into a new versioned raw path; do not overwrite the pinned working archive.
4. Import into a side-by-side processed path and build a side-by-side SQLite index.
5. Re-run both stable-ID suites. Post IDs normally remain stable, but removed or policy-changed posts require an explicit suite revision rather than silently editing old judgments.
6. Build a new semantic generation. Unchanged `content_id` values are eligible for vector reuse when the representation and model profile match.
7. Compare measurements and citations, update the registry only after the replacement passes, then reconfigure the unified MCP.

The full Stack Overflow dump should follow this process only after storage estimates are reviewed. Its much larger `Posts.xml` is why the importer stages relationships in SQLite instead of holding every title, question, answer, or user in Python memory.
