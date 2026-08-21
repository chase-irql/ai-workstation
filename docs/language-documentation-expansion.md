# Language documentation expansion

The 2026-08-20 language pass closes the largest gaps left after Python, Rust, Go, TypeScript, GCC/LLVM, .NET, and Node.js. It adds Java 26, MDN JavaScript/Web APIs, the signed ECMAScript 2026 specification snapshot, cppreference, Kotlin, PHP, Ruby 4.0, and The Swift Programming Language.

## Acquisition and provenance

GitHub-hosted corpora are pinned to immutable commits and acquired as bounded archives. The mutable PHP archive receives a local SHA-256 and full member validation. Java and Ruby use `http-site-mirror`, which stays within an explicit versioned URL prefix, stores HTML only, resumes from a persistent checkpoint, hashes every page, enforces file/byte ceilings, and atomically publishes only a complete mirror. Upstream 404/410 links are recorded as skipped; other HTTP failures stop publication.

Raw archives, mirrors, normalized JSONL, SQLite databases, vector indexes, and evaluation results stay outside Git. The public repository contains the source registry, acquisition/import code, tests, and versioned evaluation suites. Java's Oracle-hosted documentation is explicitly private local reference data and must not be redistributed with the project.

## Published generations

| Corpus | Documents | Chunks | BM25 bytes |
|---|---:|---:|---:|
| Java SE/JDK 26 | 6,266 | 59,627 | 104,337,408 |
| MDN JavaScript/Web API | 9,415 | 53,684 | 87,764,992 |
| ECMAScript 2026 | 2 | 1,783 | 2,682,880 |
| cppreference | 6,635 | 49,307 | 119,853,056 |
| Kotlin | 303 | 4,289 | 11,497,472 |
| PHP | 11,788 | 65,592 | 83,963,904 |
| Ruby 4.0 | 1,254 | 6,192 | 20,930,560 |
| Swift book | 43 | 769 | 2,961,408 |

Each database passed document/chunk/FTS count validation, foreign-key validation, and a smoke query before atomic publication. Each corpus also has a stable-document-ID lexical regression gate. These small topic gates test ingestion and retrieval continuity; they are not comprehensive measures of answer correctness.

All 241,243 chunks also have verified 256-dimensional Qwen3-Embedding generations occupying 373,516,321 bytes in total. On the same exact-topic gates, hybrid retrieval preserved Success@10 of 1.0 for every corpus while improving resilience beyond either retriever alone. These suites favor exact technical terms, so they validate cutover and source alignment rather than serving as a strong paraphrase benchmark.

| Corpus | Semantic Success@1 / @10 | Hybrid Success@1 / @10 | Hybrid MRR@10 |
|---|---:|---:|---:|
| Java SE/JDK 26 | 0.80 / 1.00 | 0.90 / 1.00 | 0.95 |
| MDN JavaScript/Web API | 0.70 / 0.90 | 0.80 / 1.00 | 0.86 |
| ECMAScript 2026 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 |
| cppreference | 0.60 / 0.80 | 0.70 / 1.00 | 0.79 |
| Kotlin | 0.40 / 0.80 | 0.70 / 1.00 | 0.81 |
| PHP | 0.40 / 1.00 | 0.80 / 1.00 | 0.88 |
| Ruby 4.0 | 0.50 / 1.00 | 0.80 / 1.00 | 0.90 |
| Swift book | 0.40 / 1.00 | 0.80 / 1.00 | 0.90 |

The ECMAScript source intentionally remains one normative specification document plus its FAQ. Its 1,783 chunks preserve clause headings and algorithms, so RAG citations resolve to clauses, but document-level recall cannot distinguish one normative clause from another. Its evaluation suite is therefore labeled a chunk smoke gate rather than a clause-ranking benchmark.

## Updating

1. Resolve a new immutable release, tag, commit, or versioned documentation prefix.
2. Review license/redistribution terms and update `config/datasets.json` before acquisition.
3. Acquire beside existing data with `acquire-dataset.ps1` or `acquire-site-mirror.ps1`; do not delete the accepted generation first.
4. Import and atomically index with `run-documentation-pilot.ps1`.
5. Run the corpus's versioned lexical suite and inspect changed citations.
6. Reuse unchanged embeddings by `content_id` where possible, then evaluate hybrid retrieval.
7. Mark the accepted registry generation and rerun `configure-knowledge-mcp.ps1 -Force`.

For site mirrors, the mirror path is a generated local artifact. For archive sources, the acquisition manifest identifies the archive hash and safe extraction inventory. An update is complete only after acquisition, parsing, indexing, evaluation, and MCP configuration all agree on the same corpus ID and source version.
