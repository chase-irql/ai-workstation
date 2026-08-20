# Stack Exchange corpus ingestion

The Stack Exchange adapter preserves each site dump's question-and-answer structure while emitting the same common document and chunk records used by the rest of the retrieval system. DevOps Stack Exchange validated the initial lifecycle; Information Security validates the same bounded-memory importer and retrieval stack at more than fourteen times the chunk count before attempting Stack Overflow.

## Pinned corpora

### DevOps Stack Exchange

- Dataset ID: `devops-stackexchange`.
- Release: coordinated community dump through June 30, 2026.
- Archive size: 18,189,978 bytes.
- Publisher/coordinated SHA-256: `a08a86c7c386c0f0798817e64ecde03368908c7ed1cf90d2259f8f209421114b`.
- Extracted archive: 10 XML files, 92,821,208 bytes.
- Imported: 5,589 questions, 2,509 accepted answers, and 3,779 other positively scored answers.
- Published: 11,877 post documents and 13,531 chunks.

### Information Security Stack Exchange

- Dataset ID: `security-stackexchange`.
- Release: coordinated community dump through June 30, 2026.
- Archive size: 271,298,857 bytes.
- Publisher/coordinated SHA-256: `401a0d754eb2a981922ddb0494648b4be57ac2cc5bad545b1fe609118df0e6df`.
- Extracted archive: 10 XML files, 1,313,984,676 bytes.
- Imported: 70,265 questions, 32,426 accepted answers, and 68,350 other positively scored answers.
- Published: 171,041 post documents and 188,770 chunks.
- BM25 index: 729,874,432 bytes; SQLite quick-check, foreign keys, document/chunk counts, FTS row count, and smoke search verified.
- Lexical gate: 18 security topics with Success@1/5/10, MRR@10, Recall@5/10/50, and nDCG@10 all `1.0`.
- Semantic generation: 188,770 verified Qwen3-Embedding vectors at 256 dimensions; 193,300,525-byte FAISS file plus 94,044,160-byte metadata database.
- Pooled paraphrase gate: hybrid Success@1 `0.357143`, Success@5 `0.857143`, Success@10 `0.928571`, Recall@50 `0.704762`, and MRR@10 `0.53869`; strict-AND BM25 scored zero on the deliberately indirect wording.
- Reranking retained Success@10 `0.928571` but lowered Success@5 to `0.785714`, so its evidence diversity should not be mistaken for a universal ranking gain.
- Routed exact-query gate: automatic routing sends terse technical phrases to strict BM25 and achieved Success@1/5/10, MRR@10, Recall@5/10/50, and nDCG@10 of `1.0`. Explicit BM25 does not apply leave-one-term-out expansion; broader questions can still use hybrid retrieval.

Downloaded dumps and generated records are intentionally excluded from Git. The registry, importer, tests, evaluation suites, and this reproducible procedure are distributed.

## Retention and identity

The importer keeps every question, every accepted answer even when its score is zero or negative, and every other answer with a positive score. Zero- and negative-score non-accepted answers are excluded. Deleted or synthetic administrative rows documented by the dump format are not treated as content.

Each retained post is its own common document. A question uses `https://{site}/questions/{id}` and an answer uses `https://{site}/a/{id}`, so citations point to the exact contribution. Answer attributes retain the parent question ID and title. Stable IDs use `{dataset_id}:post:{id}`, such as `security-stackexchange:post:276093`.

The adapter also preserves tags, post score, accepted status, view and answer counts for questions, creation/edit/activity dates, contributor ID and display name when available, and each post's exact `ContentLicense`. Rendered HTML is converted into structured text without discarding headings, lists, or code blocks.

## Build from scratch

Install the pinned Python dependencies, including `py7zr`, then run:

```powershell
.\scripts\validate-dataset-registry.ps1
.\scripts\acquire-dataset.ps1 -DatasetId security-stackexchange -Extract
.\scripts\run-stack-exchange-pipeline.ps1 -DatasetId security-stackexchange
.\scripts\evaluate-documentation.ps1 `
  -DatasetId security-stackexchange `
  -Suite rag\eval\security-stackexchange-v1.json
```

Acquisition is resumable, verifies the registered SHA-256, validates 7z member paths and sizes, and atomically publishes extraction. Import and SQLite construction likewise build beside the destination and require `-Force` before replacing recognized output.

For DevOps, the evaluated high-fidelity semantic profile uses model ID `qwen3-embedding-0.6b-1024` and lives at `indexes/semantic/devops-stackexchange-1024`. Information Security uses the 256-dimensional default: pooled evaluation already recovers relevant evidence for 13 of 14 paraphrases in the first 10, so a four-times-larger 1,024-dimensional rebuild is not currently justified. The ordinary corpus semantic script reads the destination from `config/datasets.json`:

```powershell
.\scripts\run-corpus-semantic.ps1 `
  -DatasetId security-stackexchange `
  -EmbeddingWorkers 2 `
  -Unload

.\scripts\evaluate-corpus-semantic.ps1 `
  -DatasetId security-stackexchange `
  -Suite rag\eval\security-stackexchange-semantic-v1.json `
  -Mode all `
  -Unload
```

## Query

CPU-only search requires no model:

```powershell
.\scripts\query-documentation.ps1 `
  -DatasetId security-stackexchange `
  -Query 'TLS certificate validation hostname'
```

Through MCP, filter `search_knowledge` to `corpora=["security-stackexchange"]` or `corpora=["devops-stackexchange"]`. Prefer `retrieval="bm25"` for error strings, protocol names, commands, and exact technical terms. `retrieval="hybrid"` can help broader natural-language questions after that corpus has a verified semantic generation, but the checked-in paraphrase suites record current limitations rather than hiding them.

## Update procedure

1. Identify a newer coordinated site archive and independently confirmed SHA-256.
2. Add the new release, URL, checksum, and realistic size bounds to a reviewed registry change.
3. Acquire into a new versioned raw path; do not overwrite the pinned working archive.
4. Import into a side-by-side processed path and build a side-by-side SQLite index.
5. Re-run both stable-ID suites. Post IDs normally remain stable, but removed or policy-changed posts require an explicit suite revision rather than silently editing old judgments.
6. Build a new semantic generation. Unchanged `content_id` values are eligible for vector reuse when the representation and model profile match.
7. Compare measurements and citations, update the registry only after the replacement passes, then reconfigure the unified MCP.

The full Stack Overflow dump should follow this process only after storage estimates are reviewed. Its much larger `Posts.xml` is why the importer stages relationships in SQLite instead of holding every title, question, answer, or user in Python memory.
