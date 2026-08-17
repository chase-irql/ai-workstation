# Phase 2 CPU-only Wikipedia RAG foundation

## Verified source corpus

The pinned English Wikipedia `enwiki-20260801` articles multistream dump and its index both pass the SHA1 values published in Wikimedia's checksum file.

| File | Bytes | SHA1 |
|---|---:|---|
| Articles multistream XML/BZip2 | 26,668,484,995 | `dd27f408e60d3bc864d42547fb0a0d7408249c13` |
| Multistream index | 283,588,691 | `49d4f7e965c2311a16a8ace5de74addc4687785e` |

The generated raw-corpus `manifest.json` records the pinned source URL, format, sizes, hashes, and verification time.

## CPU-only pipeline

The implementation does not invoke Ollama or load any model. It:

1. streams concatenated BZip2 XML rather than expanding the entire dump;
2. selects main-namespace pages and records redirects separately;
3. removes templates, references, media/category links, and markup;
4. preserves article identity, revision timestamp, URL, and heading hierarchy;
5. creates deterministic, content-hashed chunks bounded at 3,200 characters;
6. builds a local SQLite FTS5/BM25 index;
7. returns source-backed passages with article, section, revision, and URL citations.

## 10,000-document pilot

| Measurement | Result |
|---|---:|
| Documents | 10,000 |
| Redirects | 2,459 |
| Searchable chunks | 142,453 |
| Extraction time | 529.7 seconds |
| BM25 build time | 22.9 seconds |
| Processed JSONL size | 240.2 MiB |
| SQLite BM25 database | 621.3 MiB |

The process ran single-stream at Windows `BelowNormal` priority. XML elements are released from the parse tree after each page, keeping memory bounded for a later full pass.

## Initial lexical retrieval evaluation

The first diagnostic suite contains eight questions whose expected articles are present in the pilot. BM25 retrieves 50 candidate chunks, deduplicates them to article titles, and evaluates the first five documents.

| Metric | Result |
|---|---:|
| Recall@5 | 1.0000 |
| Mean reciprocal rank | 0.6667 |
| Mean query latency | 51.8 ms |
| Maximum query latency | 105.4 ms |

This is a plumbing baseline, not a representative Wikipedia benchmark. The pilot is biased toward early page IDs and the evaluation set is intentionally small. It does, however, demonstrate exact lexical retrieval, structured citations, deterministic rebuilding, and measurable ranking before embeddings are introduced.

## Deferred GPU/model work

- Qwen3-Embedding vector generation;
- LanceDB vector/hybrid index;
- semantic reranking;
- GLM answer synthesis;
- OpenCode/MCP integration.

Those stages remain separate so parsing and BM25 work can continue while the GPU is reserved for other applications.
