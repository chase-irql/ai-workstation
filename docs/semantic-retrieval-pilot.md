# Semantic retrieval pilot

## Outcome

The first document-level semantic pilot validates the retrieval model and hybrid strategy without altering the published full Wikipedia BM25 index or its running service.

- Source: the existing 10,000-record Wikipedia pilot.
- Searchable documents: 7,540; redirect/empty records are intentionally not embedded.
- Representation: article title plus lead chunk, capped at 4,000 characters.
- Embedding output: 256-dimensional, L2-normalized vectors.
- Vector search: exact cosine search using FAISS `IndexFlatIP`.
- Hybrid ranking: weighted reciprocal-rank fusion of distinct BM25 and semantic document rankings.
- Build time: 142.677 seconds on the RTX 5080.
- Published storage: 7.72 MB FAISS vectors plus 14.30 MB SQLite provenance.

The generation is published through an atomic `manifest.json` pointer. A failed authorized rebuild cannot replace the prior readable generation. The manifest binds the vectors to the source database/build identity, embedding configuration, representation settings, dimensions, counts, file sizes, and SHA-256 checksums.

The production builder uses an append-only float32 vector checkpoint paired with transactional SQLite metadata. Vector bytes are flushed and `fsync`ed before the matching metadata commit. On resume, the builder reconciles both files to their largest common complete prefix, truncates unmatched bytes or rows, validates the source/model/configuration identity, and continues after the last committed document ID. FAISS is constructed from the completed memory-mapped checkpoint only during final publication, avoiding repeated multi-gigabyte FAISS rewrites.

### Throughput tuning

A 512-document local benchmark compared request concurrency and batch sizes. Serial batches of 64 reached 56.74 documents/second; serial batches of 128 reached 58.51 documents/second; two concurrent batches of 128 reached 60.83 documents/second. Four workers did not materially improve on two (60.89 documents/second), indicating that the GPU was saturated. The builder therefore defaults to two bounded embedding workers and batches of 128. Results are yielded in input order, so concurrency does not change vector IDs or reproducibility.

## Measured challenge results

The immutable eight-query semantic challenge was run with 50 returned candidates per query.

| Retriever | Success@1 | Success@5 | Success@10 | MRR@10 | nDCG@10 | Mean latency |
|---|---:|---:|---:|---:|---:|---:|
| SQLite FTS5/BM25 | 0.500 | 0.625 | 0.625 | 0.5625 | 0.578866 | 10.799 ms |
| Semantic | 0.500 | 1.000 | 1.000 | 0.7500 | 0.815465 | 93.432 ms |
| Hybrid RRF | 0.625 | 1.000 | 1.000 | 0.791667 | 0.845233 | 101.941 ms |

Semantic retrieval recovered every relevant article in the top five and placed every target within the top two. Hybrid fusion retained that complete recall while improving first-position accuracy. Evidence is retained locally at `results/rag/semantic-pilot-10000-v1.json` (generated data is excluded from Git).

This is a model/fusion validation, not a claim about whole-Wikipedia approximate-nearest-neighbor recall. The pilot contains all eight challenge targets and a limited, early-page distractor population.

## Full-corpus projection

The complete SQLite index contains 19,215,907 document records but only 7,215,325 documents with searchable chunks; redirects and empty records do not need vectors. At the tuned two-worker rate, embedding those documents would take about 33 hours of uninterrupted GPU time.

A flat 256-dimensional float32 vector matrix would use about 6.88 GiB. Extrapolating the standalone pilot metadata would add about 12.75 GiB, for roughly 19.6 GiB before filesystem overhead. During construction, the resumable raw-vector checkpoint temporarily adds another 6.88 GiB. Storage is therefore safe on the current D drive. A later optimization should compare exact flat search with IVF-PQ or another FAISS ANN index on a representative shard and avoid duplicating lead text already present in the source SQLite database.

## Reproduce

From the repository root:

```powershell
.\scripts\run-wikipedia-semantic-pilot.ps1 -Unload
```

The script selects the highest-priority embedding model from `config/models.json`. Use `-Force` only to authorize replacement of an existing semantic generation.

## Primary implementation references

- [Ollama embeddings](https://docs.ollama.com/capabilities/embeddings): local batch embedding API and normalized-vector behavior.
- [Qwen3-Embedding model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B): 32K context, instruction-aware retrieval, and 32–1024 Matryoshka dimensions.
- [FAISS](https://github.com/facebookresearch/faiss): exact and approximate dense-vector similarity indexes.

## Full build and recovery

Start the complete document-level generation in the background and inspect its durable checkpoint with:

```powershell
.\scripts\run-wikipedia-semantic-full.ps1 -Background
.\scripts\get-wikipedia-semantic-status.ps1
```

If Windows, Ollama, or the build process stops, resume the common durable prefix with:

```powershell
.\scripts\run-wikipedia-semantic-full.ps1 -Resume -Background
```

Discarding an incomplete generation requires the explicit `-Restart` switch. Replacing an already published generation separately requires `-Force`; neither operation touches the BM25 database or unrelated files.

A synthetic test suite covers interruption, inconsistent raw/metadata tails, configuration mismatch, explicit restart, atomic replacement, and deterministic concurrent ordering. A real Ollama process-level test was also forcibly terminated at 1,792 documents, resumed to all 7,540 searchable pilot documents, atomically published, and returned `Albedo` as the top result for the semantic reflectivity query.

A dedicated cross-encoder reranker is not yet present; current reranking is deterministic BM25/semantic RRF. The full BM25 service remains the production endpoint until the complete semantic generation passes integrity, retrieval, latency, and agent tests.

## Serving and agent integration

The HTTP and MCP layers support explicit `bm25`, `semantic`, and `hybrid` retrieval modes. BM25 is still the safe default before full verification. Supplying a published vector directory enables the other modes without loading it immediately. Health/status requests report configuration, publication, load state, available modes, prior load errors, and query-cache statistics.

The HTTP request field is `retrieval_mode`; the MCP `search_wikipedia` argument is `retrieval`. Both use the same retrieval runtime and preserve the prior BM25 query-mode controls. Vector search is serialized around the shared read-only FAISS/SQLite metadata pair so threaded HTTP requests cannot misuse a SQLite connection. Query embedding calls remain concurrent outside that short search lock and use a bounded thread-safe LRU cache.

After the automated verifier records a passing result for the published generation:

```powershell
.\scripts\enable-wikipedia-hybrid.ps1
```

The guarded activation refuses an absent, failed, or generation-mismatched verification result. It updates the HTTP service and MCP command only after those checks, exercises a real hybrid request, and normally unloads the embedding model after the smoke test. The FAISS index occupies system RAM when first used; the query embedding model consumes GPU memory only while Ollama keeps it loaded.
