# OpenStax textbook ingestion

The OpenStax adapter imports official CollXML collection manifests and referenced CNXML modules into the corpus-neutral record schema. It does not scrape rendered web pages, execute source content, or flatten an entire book into anonymous text.

## Current corpus

`openstax-calculus` contains Calculus Volumes 1–3 from official repository commit `8dbc2ce19e804924b2517b89ac72ee45be949d15` (2026-07-15). The snapshot is licensed CC BY-NC-SA 4.0. Repository and collection notices remain with the raw archive, and every indexed document carries its book license and immutable source URL.

The downloaded archive is 134,792,906 bytes with locally measured SHA-256 `c3f589d2b20f8837f6faf8c872ea5f0702e8761097c47ab2d45889145da0b6c5`. GitHub did not publish an adjacent digest and the commit is unsigned, so this is local integrity evidence rather than publisher authentication.

Safe extraction produced 2,084 files totaling 217,389,281 bytes. The collection manifests reference 163 module occurrences. Thirty shared modules occur in adjacent volumes, so the importer publishes 133 unique documents while retaining every book, chapter, and ordinal occurrence in `book_occurrences`.

## Structure retained

The adapter preserves:

- book, chapter, nested collection, and module order;
- stable module IDs and immutable source URLs;
- section hierarchy, examples, exercises, problems, solutions, definitions, and rules;
- code, notes, lists, tables, figure alternative text, and captions;
- deterministic searchable text for common MathML fractions, powers, subscripts, and roots;
- neighboring chunk links, reusable content IDs, and occurrence-specific chunk IDs;
- per-book license text, source hashes, and module UUIDs.

Media remains in the raw snapshot for diagrams and visual inspection but is not inserted into FTS as binary content. Mathematical rendering is intended for retrieval, not lossless round-tripping or typesetting.

## Rebuild and update

Add or update the pinned commit, acquisition URL, size bounds, content subdirectory, release label, and immutable source URL template in `config/datasets.json` before downloading a new snapshot. Acquire it with the repository's bounded archive workflow and validate the recorded archive hash and safe-extraction report.

Then run:

```powershell
.\scripts\run-openstax-pilot.ps1 `
  -DatasetId openstax-calculus `
  -SourceRoot D:\ai-workstation\corpora\raw\textbooks\openstax-calculus `
  -Force

.\scripts\evaluate-documentation.ps1 `
  -DatasetId openstax-calculus `
  -Suite rag\eval\openstax-calculus-v1.json
```

`-Force` only replaces a recognized importer output directory and an explicitly authorized target index. Both replacements are built and validated before publication. Omit `-Force` for the first build; existing outputs are otherwise protected.

Verify independently:

```powershell
$env:PYTHONPATH = 'D:\ai-workstation\rag\src'
.\.venv\Scripts\python.exe -m offline_rag.verify `
  --database indexes\textbooks\openstax-calculus.sqlite3 `
  --input corpora\processed\textbooks\openstax-calculus `
  --smoke-query 'fundamental theorem calculus'
```

Never overwrite the old raw snapshot during acquisition. Download and validate a versioned replacement first, build processed records and indexes atomically, compare the stable-ID suite, and only then update the active registry entry. Keep old raw snapshots until the new build is accepted or storage policy explicitly retires them.

## Current result and limitations

The current index has 133 documents, 11,807 chunks, 11,807 FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 17,432,576 bytes. The 41-case lexical suite has Success@1/5/10, Recall@5/10/50, MRR@10, and nDCG@10 of 1.0.

The gate primarily verifies named curriculum topics and parser/index stability; it is not yet a difficult paraphrase benchmark. Semantic indexing should be added only after the existing overnight embedding queue completes and a judged conceptual suite demonstrates enough hybrid-retrieval benefit to justify its GPU time and storage.
