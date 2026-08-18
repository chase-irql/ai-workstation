# Offline RAG foundation

This package provides the CPU-only foundation for the local knowledge system:

- streaming MediaWiki XML extraction;
- structure-aware, provenance-preserving chunks;
- corpus-neutral records with a version-1 Wikipedia adapter;
- atomic SQLite FTS5/BM25 indexing and search;
- source-backed result records suitable for a later MCP tool.

Vector embeddings and LLM generation are deliberately separate stages. The Wikipedia pilot can be parsed, indexed, and searched without Ollama or GPU use.

## Pilot commands

From `D:\ai-workstation`:

```powershell
.\scripts\run-wikipedia-pilot.ps1 -MaxArticles 10000
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance computer'
```

Extraction refuses to overwrite recognized output files, and index construction refuses to replace an existing database. To intentionally rebuild the pilot, add `-Force`. The full-build script never overwrites an existing database.

Generated documents live under `corpora/processed/wikipedia/`; search indexes live under `indexes/wikipedia/`. Both are excluded from Git and can be rebuilt from the verified raw dump.

## Full Wikipedia build

The full build uses the Wikimedia multistream index to extract independent bzip2 blocks with a CPU process pool, then creates the complete BM25 database. It does not load an LLM or require the GPU.

```powershell
.\scripts\run-wikipedia-full.ps1
.\scripts\get-wikipedia-full-status.ps1
```

The full corpus is written to `corpora/processed/wikipedia/enwiki-20260801/full/`; the completed index will be `indexes/wikipedia/enwiki-20260801-full.sqlite3`.
Workers publish private Zstandard-compressed document and chunk shards atomically. The default planner targets 8 MiB of compressed input per part with a ceiling of 128 blocks, producing deterministic, balanced work without shared append files. After an interruption, continue with `.\scripts\run-wikipedia-full.ps1 -Resume`. Resume verifies completed shard hashes by default; `-QuickResume` verifies recorded sizes only.

The wrapper defaults to eight workers and enforces a 15% free-space reserve before SQLite indexing. Override these deliberately with `-Workers`, `-TargetPartMiB`, or `-MinimumFreePercent`. Use `-ExtractionOnly` to stop after publishing the compressed corpus.

## Extraction states

`extraction-stats.json` and the checkpoint distinguish `archive_complete`, `article_limit`, `interrupted`, and `failed`. Only `archive_complete` sets `completed` to true. Ctrl+C finishes the current document, durably checkpoints, and exits with status 130. `--force` replaces only recognized extraction artifacts and leaves unrelated files in the output directory untouched.

Version-1 Wikipedia JSONL and safely verifiable version-1 checkpoints remain readable. Version-1 checkpoints that were incorrectly marked complete by a limited legacy run cannot be safely distinguished from real archive completion and should not be resumed without independent verification.

## Index and query behavior

The index reads legacy uncompressed JSONL or the ordered compressed-shard manifest directly; no large merge file is created. It is built into a temporary SQLite database in the destination directory. Counts, foreign keys, FTS rows, integrity, and a smoke query are validated before an authorized atomic replacement. Chunk text is stored once in the relational table while the contentless FTS table stores only its search index. Use `--overwrite` only when replacement is intentional. Interrupted or failed extraction output requires the explicit `--allow-incomplete` build option.

The default query mode is `and`:

```powershell
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance computer' -Mode and
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance' -Mode phrase
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance' -Mode or
```

`exact` is an alias for tokenizer-level phrase matching; it is not byte-for-byte punctuation matching. Version-2 indexes add deterministic aliases for `C++`, `C#`, `.NET`, scoped names such as `std::vector`, and underscore identifiers such as `foo_bar`. For `and` and `or` queries, a small documented set of English question scaffolding (`what`, `is`, `the`, and similar terms) is removed when meaningful terms remain. Phrase and exact modes retain every token. An indexed exact-title lookup is promoted ahead of ordinary BM25 results when the remaining query terms equal a document title. Every result preserves the original query, normalized terms, raw retrieval score, and a `ranking_reason` of `exact_title` or `bm25`.

## Evaluation

Legacy suites containing `expected_titles` remain supported. Version-2 suites require stable query IDs and graded relevance keyed by document ID. Results include document-level Success@1/5/10, Recall@5/10/50 when configured, MRR@10, nDCG@10, query-type groups, and latency percentiles. Index build identity and a suite hash are embedded for comparison. `rag/eval/wikipedia-full-v2.json` is the gating lexical/entity-lookup smoke suite for SQLite BM25; `rag/eval/wikipedia-semantic-challenge-v2.json` preserves paraphrase questions as a non-gating baseline for the future vector and reranking stages.

See `docs/rag-record-schema.md` for the common record contract and `docs/wikipedia-multistream-design.md` for the parallel extraction design and recovery model.
