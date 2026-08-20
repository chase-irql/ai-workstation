# Unified offline knowledge MCP

The `offline-knowledge` MCP server federates independently versioned indexes instead of merging them. A failed or replaced documentation index therefore cannot invalidate Wikipedia or another corpus, and each corpus retains its own build metadata, source version, citations, and evaluation history.

## Published corpora

The current OpenCode configuration exposes:

- `wikipedia`: English Wikipedia 2026-08-01, with BM25 and the published semantic/hybrid generation;
- `python-3.14-docs`: Python 3.14.7 documentation;
- `git-docs`: Git 2.55.0 documentation;
- `linux-man-pages`: Linux man-pages 6.18;
- `rfc-editor-text`: RFC Editor text snapshot 2026-08-19;
- `iana-protocol-registries`: IANA assignments snapshot 2026-08-19;
- `sqlite-docs`: SQLite 3.53.4 documentation.

Python, Git, Linux man-pages, RFC Editor, and SQLite have independently published chunk-level semantic generations. Wikipedia retains its article-level semantic generation, while IANA remains BM25/structured-first. All semantic resources are lazy: server startup and `knowledge_index_status` do not invoke Ollama or load an embedding model. A caller can request `retrieval: "bm25"` to guarantee a CPU-only search. If a semantic backend is unavailable, the federated tool reports the reason and explicitly falls back to BM25 for that corpus.

IANA is table-aware: each nested registry is a document and each registry record is independently searchable with its field names, references, stable IANA URL fragment, and CC0 provenance. Exact ports, protocol numbers, media types, and cipher-suite identifiers should use BM25 and a corpus filter. See `docs/corpus-semantic-roadmap.md` for why registry rows are not the first embedding target.

## Tools

`search_knowledge` searches every corpus by default. Its optional `corpora` array restricts work when the source is known. `retrieval="auto"` is the default: exact identifiers, quoted phrases, and IANA lookups stay on BM25, while conceptual language uses hybrid retrieval wherever a verified vector generation exists. Explicit `bm25`, `semantic`, `hybrid`, and legacy `default` selections remain available. The MCP-facing result limit is clamped to 1-20 and reports the requested and effective values; the evaluation runtime may request as many as 50 candidates. Each result includes `knowledge_corpus`, `document_id`, `chunk_id`, evidence text, source version, URL, and a ready-to-use citation.

`retrieve_knowledge_context` accepts the result's `knowledge_corpus` and `chunk_id`, then returns a bounded neighboring window. This is the preferred expansion tool.

`retrieve_knowledge_document` returns a small paginated document read. It requires the corpus and stable document ID and safely clamps page size.

`knowledge_index_status` reports each database's build identity, version, document/chunk counts, available retrieval modes, and semantic load state.

BM25 magnitudes are not comparable across databases with radically different sizes. Cross-corpus candidate generation therefore begins with deterministic reciprocal rank by corpus. The `deterministic-evidence-v2` reranker keeps that semantic/hybrid rank dominant and uses bounded title, heading, passage, identifier, exact-title, and dual-retrieval evidence as transparent tie-breakers over a 32–50 document pool. Common question scaffolding is excluded from coverage calculations. Exact `content_id` duplicates and passages with at least 0.92 token Jaccard overlap are suppressed before applying the final result limit. A retained result records `alternate_sources` and `alternate_document_ids` when equivalent evidence occurred in another document, so deduplication does not erase a valid citation or evaluation judgment. Source BM25/vector scores, per-corpus ranks, rerank components, routing reasons, and removed duplicates remain visible.

Evaluate the actual routed, fused, reranked, and deduplicated path with:

```powershell
.\scripts\evaluate-reranked-corpus.ps1 `
  -DatasetId rfc-editor-text `
  -Suite rag\eval\rfc-editor-semantic-v2.json `
  -Output results\rag\semantic\rfc-editor-text-reranked-v2.json `
  -Unload
```

The output is written atomically and includes the suite hash, per-query rankings, grouped metrics, latency percentiles, source database, vector manifest, and reranker version.

## Configure and use OpenCode

From the repository root:

```powershell
.\scripts\configure-knowledge-mcp.ps1 -Harness opencode
.\scripts\start-opencode.ps1
```

Restart an already-open OpenCode session so it discovers the new tools. The existing `offline-wikipedia` entry is deliberately retained for compatibility.

Example prompt:

```text
Use the offline knowledge tools to explain the TLS 1.3 key schedule. Search the RFC corpus first, retrieve nearby context where needed, distinguish the current specification from obsolete RFCs, and preserve exact source citations.
```

Exact IANA lookup example:

```text
Use search_knowledge with corpora=["iana-protocol-registries"] and retrieval="bm25" to identify the assigned TCP port for HTTPS. Cite the exact IANA registry result.
```

For a CPU-only request, tell the agent to pass `retrieval=bm25`. The local language model used by OpenCode is independent of the retrieval server. Semantic requests load only the configured embedding model; the chat model is unaffected.

## Adding another corpus

An independently built dataset becomes eligible after its registry status is `evaluated` and its SQLite index exists at `paths.index`. Re-run:

```powershell
.\scripts\configure-knowledge-mcp.ps1 -Harness opencode -Force
```

The configuration script validates every evaluated index before replacing the `offline-knowledge` command. New corpora must complete acquisition validation, corpus-specific parsing, atomic BM25 construction, and their versioned evaluation gate before registration. Semantic indexing is a later, independently published stage and is not required for exact-search availability.
