# Offline RAG foundation

This package provides the CPU-only foundation for the local knowledge system:

- streaming MediaWiki XML extraction;
- structure-aware, provenance-preserving chunks;
- corpus-neutral records with a version-1 Wikipedia adapter;
- atomic SQLite FTS5/BM25 indexing and search;
- atomic document-level FAISS semantic indexes with SQLite provenance;
- deterministic BM25/semantic reciprocal-rank fusion;
- source-backed result records suitable for a later MCP tool.

The lexical baseline remains usable without Ollama or GPU use. Semantic indexing and queries are a separate optional stage and do not modify the published BM25 database.

## Corpus-neutral documentation

`offline_rag.documentation` converts structured documentation trees to the common record contract without changing the version-1 Wikipedia path. It supports HTML, Markdown, reStructuredText, AsciiDoc, man/roff, numbered RFC text, and plain text; preserves headings, code, tables, provenance, versions, licenses, and neighbor links; and publishes output atomically. `offline_rag.iana` provides a table-aware importer for nested IANA registry XML and one-record-per-chunk exact retrieval. `offline_rag.acquisition` and `offline_rag.rsync_acquisition` provide resumable, integrity-checked acquisition, while `config/datasets.json` records the planned source and storage contract.

Python 3.14.7, Git 2.55.0, Linux man-pages 6.18, the RFC Editor 2026-08-19 text snapshot, and the IANA assignments snapshot are queryable with `scripts/query-documentation.ps1`. Their versioned lexical and semantic gates live under `rag/eval/`. Python, Git, man-pages, and RFCs have published chunk-level semantic indexes; IANA remains BM25/structured-first. See `docs/documentation-corpus-ingestion.md` for their exact lifecycle and `docs/corpus-semantic-roadmap.md` for measured embedding results.

`offline_rag.knowledge_mcp_server` federates those indexes with Wikipedia through a read-only MCP interface. Cross-corpus search uses deterministic per-corpus reciprocal-rank fusion because raw BM25 scores from differently sized databases are not directly comparable. Corpus-filtered search, bounded context/document retrieval, build status, lazy Wikipedia semantic retrieval, and explicit BM25 fallback are exposed without merging or rewriting the source indexes. See `docs/unified-knowledge-mcp.md`.

`offline_rag.chunk_vector_index` builds a separate vector for every documentation chunk using its title, heading path, and text. Generations are resumable, source-build-bound, checksum-verified, reusable by exact representation fingerprint, and atomically published. Build or compare one registered corpus with:

```powershell
.\scripts\run-corpus-semantic.ps1 -DatasetId python-3.14-docs
.\scripts\get-corpus-semantic-status.ps1
.\scripts\evaluate-corpus-semantic.ps1 `
  -DatasetId python-3.14-docs `
  -Suite rag\eval\python-docs-semantic-v1.json
```

The unified MCP supports multiple independent semantic generations. `retrieval=auto` keeps exact technical identifiers on BM25 and uses hybrid retrieval for conceptual language; the transparent `deterministic-evidence-v2` reranker and provenance-preserving duplicate suppression run before the final result limit. Evaluate that complete path with `scripts/evaluate-reranked-corpus.ps1`; unlike the lower-level semantic comparison, it measures routing, fusion, reranking, and deduplication together.

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

## Local Wikipedia service

The complete index can run as a persistent read-only browser and JSON service:

```powershell
.\scripts\start-wikipedia-service.ps1 -Background
.\scripts\get-wikipedia-service-status.ps1
.\scripts\stop-wikipedia-service.ps1
```

The default URL is `http://127.0.0.1:8765/`. API endpoints are:

- `GET /health` or `GET /v1/status` for readiness and index metadata;
- `GET /v1/search?q=apollo+program&mode=and&limit=8`;
- `POST /v1/search` with `{"query":"Apollo program","mode":"and","limit":8}`;
- `GET /v1/documents/enwiki%3A1461?offset=0&limit=20` for ordered source chunks.

The search body also accepts `retrieval_mode` with `bm25`, `semantic`, or `hybrid`. BM25 remains the default unless a verified semantic generation is explicitly enabled. Semantic resources are lazy: service startup and health checks do not load FAISS or invoke Ollama. The first semantic/hybrid request loads the vector index into system RAM and invokes the local embedding model; a bounded in-memory LRU avoids regenerating embeddings for repeated query strings.

After full semantic verification passes, perform the guarded service and MCP cutover with:

```powershell
.\scripts\enable-wikipedia-hybrid.ps1
```

The activation script requires a passing verification status bound to the published generation, restarts the HTTP service with hybrid as its default, updates the selected MCP harness configuration, runs a real hybrid smoke query, and unloads the embedding model afterward by default. BM25 remains selectable and works without Ollama or GPU access.

Requests are bounded, the service has no write endpoints, and it binds only to localhost by default. Binding to `0.0.0.0` makes it reachable from the LAN and should be done only on a trusted network; this initial service does not provide authentication or TLS.

## Agent access through MCP

The same read-only index is exposed as a local stdio MCP server with four tools:

- `search_wikipedia` returns distinct, cited Wikipedia documents;
- `retrieve_wikipedia_context` expands one search hit with a small neighboring window;
- `retrieve_wikipedia_document` returns a deliberately small ordered page from a selected document;
- `wikipedia_index_status` reports the corpus version, build identity, and counts.

When semantic retrieval is configured, `search_wikipedia` accepts `retrieval` as `default`, `bm25`, `semantic`, or `hybrid`. This adds no new tool names, so existing agents and prompts remain compatible.

Exact-title promotion returns the article's lead chunk instead of an arbitrary short section. Agents are instructed to use the evidence already present in search results and prefer neighboring-context retrieval, preventing whole-article reads from consuming the model context window.

For strict AND queries of four or more terms that lack an exact-title hit, the agent/API layer performs bounded leave-one-term-out retrieval and reciprocal-rank fusion. If a candidate title is contained in the original query, it is resolved back to the canonical lead passage. This recovers from one hallucinated or overly specific term while preserving strict deterministic BM25 as the primary query. Oversized MCP context requests are safely clamped and reported instead of wasting context or forcing a correctable failed tool call.

The human-facing CLI and HTTP API retain explicit `or` mode. It is intentionally omitted from the MCP tool schema: unrestricted OR over tens of millions of chunks can be dominated by a common term and exceed an agent timeout. Agents use strict AND, phrase, or exact search plus the bounded relaxation above.

Configure both installed agent harnesses from the repository root:

```powershell
.\scripts\configure-wikipedia-mcp.ps1
```

Launch the interactive OpenCode workspace with the configured Ollama provider, default general-agent model, and project MCP settings by running:

```powershell
.\scripts\start-opencode.ps1
```

Pass `-ModelId` to select another model from `config/models.json`. Inside OpenCode, `/models` lists the models exposed by the configured local provider.

The root `opencode.json` is the operational OpenCode configuration. Codex registration is written by its CLI to the current user's Codex configuration. Neither path changes the immutable benchmark profiles under `config/harnesses/`. The MCP server starts on demand, reads the published SQLite database in read-only mode, and does not load Ollama or use the GPU.

The model-and-tool evaluation verifies more than process exit: it requires the model to call the expected MCP tools, retrieve stable document IDs, include expected facts, emit a Wikipedia citation, and make no failed tool calls. It selects the highest-priority general-agent model from `config/models.json` unless `-ModelId` is supplied:

```powershell
.\scripts\evaluate-wikipedia-agent.ps1
.\scripts\evaluate-wikipedia-agent.ps1 -ModelId glm-4.7-flash -Unload
.\scripts\evaluate-wikipedia-agent.ps1 -CaseId apollo-guidance-computer -Unload
```

The current versioned prompts and deterministic concept assertions are in `rag/eval/wikipedia-agent-v2.json`; the original v1 exact-term suite remains available for historical comparison. Generated evidence is retained under the ignored `results/rag/agent-e2e/` directory.

See `docs/rag-record-schema.md` for the common record contract and `docs/wikipedia-multistream-design.md` for the parallel extraction design and recovery model.

## Semantic retrieval pilot

The semantic stage selects its embedding model from `config/models.json`, publishes generation-specific FAISS and provenance files behind an atomic manifest, and supports pure semantic or hybrid BM25/vector retrieval. Build and evaluate the 10,000-record pilot with:

```powershell
.\scripts\run-wikipedia-semantic-pilot.ps1 -Unload
```

The measured pilot raised Success@10 on the semantic challenge from 0.625 for BM25 to 1.0 for both semantic and hybrid search. See `docs/semantic-retrieval-pilot.md` for exact metrics, storage projections, limitations, and recovery behavior.

Full semantic construction is resumable and runs independently of the existing BM25 service:

```powershell
.\scripts\run-wikipedia-semantic-full.ps1 -Background
.\scripts\get-wikipedia-semantic-status.ps1
```

Raw vector bytes are durably written before their SQLite provenance rows are committed. Resume reconciles both checkpoint files to their common complete prefix and validates the source database, embedding model, dimensions, representation, and execution settings before continuing. Use `-Resume` after interruption or the explicit `-Restart` switch to discard only the recognized incomplete semantic generation.

## Updating Wikipedia

New dumps are built beside the serving generation. After building the new BM25 database, calculate the exact semantic delta without loading a model, then reuse unchanged vectors:

```powershell
.\scripts\plan-wikipedia-update.ps1 -PreviousDumpDate 20260801 -DumpDate 20260901
.\scripts\run-wikipedia-semantic-full.ps1 -DumpDate 20260901 -ReuseFromDumpDate 20260801 -Background
```

Reuse requires matching stable document IDs, exact embedding-input hashes, provider identity, dimensions, and representation settings. New source and citation metadata is always written even when the vector is copied. See `docs/wikipedia-corpus-updates.md` for the complete download, build, verification, cutover, rollback, and compatibility process.
