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

The complete SQLite index contains 19,215,907 document records but only 7,215,325 documents with searchable chunks; redirects and empty records do not need vectors. At the measured pilot rate, embedding those documents would take about 38 hours of uninterrupted GPU time.

A flat 256-dimensional float32 vector matrix would use about 6.88 GiB. Extrapolating the standalone pilot metadata would add about 12.75 GiB, for roughly 19.6 GiB before filesystem overhead. Storage is acceptable, but a multi-day build must gain durable resume support before it is launched. A production design should also compare exact flat search with IVF-PQ or another FAISS ANN index on a larger representative shard, and should avoid duplicating lead text already present in the source SQLite database.

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

## Remaining gate before a full build

Implement resumable raw-vector checkpoints and validate a production FAISS index on a larger, representative corpus sample. A dedicated cross-encoder reranker is not yet present; current reranking is deterministic BM25/semantic RRF. The full BM25 service remains the production endpoint until a complete semantic generation passes the same integrity, retrieval, and agent tests.
