# Corpus semantic retrieval roadmap

The newly published documentation and IANA corpora are intentionally usable before embeddings exist. Their SQLite FTS5/BM25 indexes are the durable exact-search baseline, and the unified MCP server can query them without loading Ollama or using the GPU.

## Implementation status

The shared `title-heading-chunk-v1` builder is implemented in `offline_rag.chunk_vector_index`. Python 3.14, Git 2.55, and Linux man-pages 6.18 have published and independently verified 256-dimensional generations covering all 26,948 chunks. RFC Editor has also published and verified 348,831 vectors covering 9,822 documents through the same resumable path. SQLite 3.53.4 now adds a verified generation for all 4,384 documentation chunks.

The original exact-term suites retained Success@1 and MRR@10 of 1.0 for BM25, semantic, and hybrid retrieval. Hybrid nDCG@10 improved from 0.922776 to 0.936714 for Python and from 0.882939 to 0.914106 for Git; Linux remained 1.0. On 12 deliberately paraphrased conceptual questions, strict AND BM25 returned no relevant documents, while semantic/hybrid found relevant evidence within the first 10 results for 10 cases and within the first 50 for every case.

RFC exact-query hybrid retrieval retained Success@1, Success@10, MRR@10, and Recall@10 of 1.0 while improving nDCG@10 from 0.903258 for BM25 to 0.916240. The final routed/reranked path retains every exact-query document at rank 1 and raises nDCG@10 to 0.929338.

The original six-query paraphrase gate initially found five cases in the first 10. `deterministic-evidence-v2` now finds all six in the first 10, with Success@5 of 0.833333 and MRR@10 of 0.546296. The former TCP miss exposed two issues: lexical rerank bonuses were overpowering good semantic ranks, and evidence deduplication could hide an equivalent RFC revision's document ID. Version 2 caps lexical tie-breaking at 0.0015, removes question scaffolding from coverage, and preserves alternate document provenance.

The expanded 18-query RFC suite covers HTTP caching, DoH, WebSocket, OAuth PKCE, IPv6 neighbor discovery, SMTP STARTTLS, CBOR, JSON Merge Patch, BCP 47, HTTP/3, ACME, and TOTP in addition to the original six. Against the raw hybrid path, the final reranked path improves Success@1 from 0.222222 to 0.277778, Success@5 from 0.777778 to 0.888889, Success@10 from 0.888889 to 0.944444, Recall@5 from 0.722222 to 0.833333, MRR@10 from 0.452778 to 0.498765, and nDCG@10 from 0.504786 to 0.515379. The remaining labeled miss is the deliberately indirect DoH query. It returns genuinely related encrypted-DNS RFCs, including Oblivious DNS over HTTPS, but the suite currently labels only the base DoH RFC; future pooled judgments and candidate-generation tuning should separate a retrieval miss from incomplete relevance labels. These small gates validate the retrieval path, not broad corpus quality.

DevOps Stack Exchange adds a different retrieval profile. Its 19-case exact-term gate is perfect at every Success, MRR, and Recall cutoff, with nDCG@10 of 0.95525 and roughly 1.4 ms mean latency. On 14 deliberately indirect paraphrases, strict-AND BM25 returns no candidates. The 256-dimensional hybrid generation reaches Success@10 0.428571 and Recall@50 0.583333; the full 1,024-dimensional profile improves those measurements to 0.571429 and 0.642857. That gain justifies the larger vectors for this small corpus, but the remaining misses show that a single 0.6B embedding model plus deterministic fusion is not sufficient for robust question-answer paraphrase retrieval. The corpus therefore remains BM25-first for exact technical searches while the hybrid path is exposed as experimental and measured honestly.

Mixed dimensions are supported deliberately rather than through a global accidental override. The federated server reads each vector manifest's provider identity, resolves that exact model profile from `config/models.json`, validates the full identity before serving, and shares a cached provider only among compatible corpora. This keeps existing 256-dimensional generations usable alongside the DevOps 1,024-dimensional generation.

SQLite's 20-query exact gate favors BM25: Success@1 is 0.95, Success@5/10 and Recall@50 are 1.0, MRR@10 is 0.975, and nDCG@10 is 0.966274 at about 1 ms mean latency. The routed/reranked path preserves those success and recall measurements and raises nDCG@10 to 0.975033. On 12 deliberately paraphrased SQLite questions, strict-AND BM25 returns no candidates; warm hybrid retrieval reaches Success@1 0.583333, Success@5 0.833333, Success@10 0.916667, and Recall@50 1.0 at about 135 ms mean latency. Deterministic reranking raises Success@5 to 0.916667 but lowers top-rank metrics, so exact identifiers remain BM25-first and reranking is treated as an evidence-diversity stage rather than a universal score improvement. The one labeled rank-10 miss is an indirect immutable/read-only query, which is found by rank 50.

## Why embedding does not happen during ingestion

Acquisition, parsing, lexical indexing, semantic indexing, and evaluation are separate publication stages. This keeps a failed model run from invalidating source records or a working BM25 index, permits embedding models to be replaced independently, and lets unchanged `content_id` values reuse cached vectors after a corpus update.

The existing Wikipedia semantic generation embeds one representation per article: title plus lead text. That representation is appropriate for article discovery but is not appropriate for long documentation or RFCs. A term explained deep inside an RFC or manual would be invisible if only its first chunk were embedded.

## Planned representation

Add a corpus-neutral, section/chunk-level semantic builder before embedding the new prose corpora. Each vector record should contain:

- a short corpus and document-title prefix;
- the complete heading path;
- one normalized chunk body;
- the stable `chunk_instance_id`, `document_id`, and `content_id`;
- source version, citation, and embedding-input hash;
- embedding provider, model, dimensions, and normalization settings.

Vectors are cached by `content_id` plus the exact representation/model configuration. The occurrence metadata remains separate, so identical reusable content can retain different document locations and citations. Generations use the same checkpoint, checksum, validation, and atomic-publication rules as the Wikipedia semantic index.

## Rollout order

1. **Python, Git, and Linux man-pages pilot — complete.** These corpora total 26,948 chunks and passed structural, exact-query, and paraphrase gates.
2. **RFC Editor collection — complete.** All 348,831 chunks are embedded in the durable checkpoint format, verified against the source build, and evaluated with exact and paraphrase suites.
3. **Federated hybrid retrieval — active.** The knowledge server accepts repeatable corpus-to-vector mappings and fuses lexical and semantic ranks within each corpus before cross-corpus ranking. The published configuration has verified semantic mappings for Wikipedia, Python, Git, man-pages, RFCs, SQLite, and DevOps Stack Exchange.
4. **Reranking and evidence packing — active.** `deterministic-evidence-v2` operates on a bounded 32–50 document pool. It preserves first-stage semantic/hybrid ordering as the dominant signal, applies capped lexical and exact-identifier evidence, and retains alternate citations when exact-content or high-overlap evidence is collapsed before the final limit.
5. **IANA routing.** Keep individual registry rows BM25/structured-first. Exact port numbers, protocol numbers, media types, cipher-suite codes, and identifiers are lexical/table lookups. Optionally embed registry titles and descriptions later for conceptual discovery, then use exact lookup inside the selected registry.

At 256 float32 dimensions, the raw vector matrix is about 26 MiB for Python/Git/man-pages and 341 MiB for RFCs. The published RFC generation occupies 357,202,989 bytes for FAISS plus 176,652,288 bytes for metadata. IANA would require roughly 112 MiB of raw vectors if embedded later. Metadata, checkpoints, and replacement headroom add overhead, but the complete documentation/RFC semantic set remains comfortably below a few gigabytes.

## Query routing

- Exact identifiers, error codes, commands, option names, RFC numbers, ports, protocol numbers, and quoted text: BM25 or structured lookup first.
- Natural-language concepts, paraphrases, and questions whose wording differs from the source: hybrid retrieval.
- Known source: pass a corpus filter to avoid unrelated evidence.
- Ambiguous cross-domain research: federated hybrid search, followed by reranking.

BM25 always remains available as the no-model fallback. The embedding model is needed only while generating vectors or embedding a semantic query; it does not need to remain loaded while source ingestion or lexical indexing runs.

## Acceptance gates

Do not activate a semantic generation merely because it builds successfully. Require:

- structural validation and exact binding to the source BM25 build;
- deterministic resume and atomic replacement tests;
- stable citations and neighboring-context retrieval;
- comparison against the same versioned BM25 evaluation suite;
- added paraphrase/conceptual cases that lexical search is expected to miss;
- no material regression on exact technical queries;
- recorded latency, disk use, vector count, and model identity.

The activation script publishes only vector generations whose manifests exist and whose source databases remain registered. Query-time semantic resources stay lazy, so OpenCode startup and BM25-only requests do not load the embedding model.
