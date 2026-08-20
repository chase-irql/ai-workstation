# Corpus catalog

This catalog is the human-readable inventory of every corpus currently published by the development installation. The repository contains acquisition metadata, importers, and evaluation suites; it intentionally does not redistribute source archives, processed records, indexes, or vectors.

`config/datasets.json` is the machine-readable registry for documentation and structured datasets. Wikipedia retains its own dump manifest because its multistream acquisition and update lifecycle are different. Generated acquisition manifests, corpus manifests, SQLite metadata, vector manifests, and evaluation reports are the run-specific evidence behind this summary.

## Published corpora

| Corpus ID | Pinned source | License / terms | Local scale | Retrieval |
|---|---|---|---:|---|
| `wikipedia` | English Wikipedia `enwiki-20260801` | CC BY-SA 4.0 and GFDL; Wikimedia attribution requirements apply | 7,215,325 searchable articles; 35.8M chunks | BM25 + article-level semantic/hybrid |
| `python-3.14-docs` | Python 3.14.7 HTML documentation | PSF License 2.0; examples additionally 0BSD | 565 documents; 8,840 chunks | BM25 + chunk-level semantic/hybrid |
| `git-docs` | Git 2.55.0 source documentation | GPL-2.0-only with Git documentation terms | 985 documents; 4,953 chunks | BM25 + chunk-level semantic/hybrid |
| `linux-man-pages` | Linux man-pages 6.18 | Per-page licenses retained in the source | 1,245 documents; 13,155 chunks | BM25 + chunk-level semantic/hybrid |
| `rfc-editor-text` | RFC Editor snapshot 2026-08-19 | IETF Trust Legal Provisions | 9,822 RFCs; 348,831 chunks | BM25 + chunk-level semantic/hybrid |
| `iana-protocol-registries` | IANA assignments snapshot 2026-08-19 | CC0 1.0 Universal | 4,256 registries; 110,423 table records; 114,590 chunks | Structured BM25 |
| `sqlite-docs` | SQLite 3.53.4 static HTML documentation | Public domain | 765 documents; 4,384 chunks | BM25 + chunk-level semantic/hybrid |
| `devops-stackexchange` | DevOps Stack Exchange 2026-06-30 community dump | CC BY-SA 3.0 or 4.0 per retained post | 11,877 retained posts; 13,531 chunks | BM25 + experimental 1,024-dim semantic/hybrid |

Counts describe the pinned local generations, not upstream projects in perpetuity. Evaluation suites are small, versioned regression gates rather than broad claims about corpus completeness or answer accuracy.

## Provenance and update records

### English Wikipedia

- Raw source: `corpora/raw/wikipedia/enwiki-20260801/`.
- Processed generation: `corpora/processed/wikipedia/enwiki-20260801/full/`.
- BM25 index: `indexes/wikipedia/enwiki-20260801-full.sqlite3`.
- Semantic generation: `indexes/wikipedia/enwiki-20260801-semantic-full/`.
- Publisher verification: Wikimedia SHA1 for both the multistream XML/BZip2 archive and multistream index.
- Update procedure: [wikipedia-corpus-updates.md](wikipedia-corpus-updates.md).

### Python documentation

- Official archive: `https://docs.python.org/3/archives/python-3.14-docs-html.zip`.
- Local archive SHA-256: `9306da398ae5a9142deb22d5c7865994fe0ada961022c8dea8ee341348e14181`.
- The publisher archive listing did not supply a digest; ZIP member CRCs and structure are validated and the local digest pins the acquired artifact.
- Processed/index paths and update frequency are recorded under `python-3.14-docs` in `config/datasets.json`.

### Git documentation

- Official archive: kernel.org Git 2.55.0 release source.
- Publisher SHA-256: `457fdb04dc8728e007d4688695e6912e6f680727920f2a40bf11eacc17505357`.
- The importer preserves AsciiDoc/man structure, relative source paths, and version-pinned kernel.org citations.

### Linux man-pages

- Official archive: kernel.org man-pages 6.18 release.
- Publisher SHA-256: `c934fadc8b59748c68227a34f6581d2ddf8282b73cdcd52546c8cd88b74b24d1`.
- Alias pages are not duplicated; per-page license notices remain in source text and provenance.

### RFC Editor

- Acquisition: official `rsync://rsync.rfc-editor.org/rfcs-text-only` snapshot.
- Source inventory: 10,057 regular files, 555,449,714 bytes, aggregate SHA-256 `8d575f0b1785b6c5ac710f48ce7c4ee129e9d79d81f7e7686726f2a23f4d3ac2`.
- The importer preserves RFC number, publication status/date, ISSN, obsoletes, updates, section hierarchy, and stable RFC Editor citations.

### IANA protocol registries

- Acquisition: official `rsync://rsync.iana.org/assignments` snapshot.
- Source inventory: 8,269 regular files, 70,672,402 bytes, aggregate SHA-256 `7c8e859136528cfe12aab4840f837ede1d8054541c50a7126cdcb8c05257b462`.
- The table-aware importer preserves nested registries, field names, row values, references, timestamps, and stable IANA URL fragments. It remains BM25-first because ports, protocol numbers, media types, and parameter codes are primarily exact lookups.

### SQLite documentation

- Official archive: `https://www.sqlite.org/2026/sqlite-doc-3530400.zip`.
- Publisher SHA3-256: `7ccf86a52e7dd1fb9b31e63edcebe3b553f18f89cd26eef59c7f191a5111836e`.
- Local archive SHA-256: `a1d0f5de57485d062796ed7e67daff0758b50d00001a0f233a2c15aaf40bbdc8`.
- The HTML importer preserves headings, code, lists, API identifiers, SQL terms, and stable `sqlite.org` citations while excluding navigation and search furniture.

### DevOps Stack Exchange

- Archive: June 30, 2026 coordinated community release hosted by Internet Archive.
- Publisher/coordinated SHA-256: `a08a86c7c386c0f0798817e64ecde03368908c7ed1cf90d2259f8f209421114b`.
- The importer retains every question, every accepted answer regardless of score, and other answers only when their score is positive. It excluded 1,503 answers under that policy.
- Each retained post is a separate document with a direct question or answer URL. Parent-question relationships, accepted status, title, tags, score, dates, contributor attribution, exact `ContentLicense`, HTML headings, lists, and code blocks are preserved.
- The 19-case exact-term suite passes every Success, MRR, and Recall cutoff. The 1,024-dimensional paraphrase gate reaches Success@10 `0.571429` and Recall@50 `0.642857`; semantic retrieval is published for experimentation, not presented as a solved quality problem.
- Acquisition and update procedure: [stack-exchange-ingestion.md](stack-exchange-ingestion.md).

## Lifecycle and publication rules

Every new or updated corpus must pass the same observable stages:

1. Register its official source, pinned version/snapshot, license, scope, size bounds, paths, and update frequency.
2. Acquire resumably and publish atomically only after size, format, and available publisher-checksum validation.
3. Parse with a corpus-specific adapter into the shared document/chunk schema while retaining provenance and structure.
4. Build a replacement SQLite database beside the live index, validate it, then atomically publish it.
5. Run a stable-ID lexical evaluation suite and inspect citations.
6. Add semantic retrieval only when conceptual discovery is useful; publish vectors independently after source-identity and row-count verification.
7. Compare BM25, semantic, hybrid, and routed/reranked behavior before exposing the generation through MCP.

Generated data remains ignored by Git. Only code, registry entries, evaluation suites, and documentation are intended for repository distribution. See [data-distribution-policy.md](data-distribution-policy.md).
