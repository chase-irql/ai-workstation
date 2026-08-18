# Wikipedia model-and-tool verification

Verified on 2026-08-18 with OpenCode 1.18.18, GLM-4.7-Flash Q4_K_M, the local stdio MCP server, and the completed `enwiki-20260801` SQLite index.

## Result

The final version-1 agent suite passed all three cases:

| Case | Result | Tool calls | Failed calls | Maximum input tokens | Time |
|---|---:|---:|---:|---:|---:|
| Apollo Guidance Computer | pass | 2 | 0 | 10,242 | 40.928 s |
| Albedo definition | pass | 2 | 0 | 10,061 | 23.347 s |
| C# / .NET technical aliases | pass | 3 | 0 | 16,529 | 27.223 s |

Every answer retrieved the expected stable document ID, contained the required facts, and emitted an exact citation returned by the local tool. No web search was enabled. The model was unloaded after the run.

## Defects found and corrected

The first Apollo trial fetched 30 article chunks and reached 23,512 input tokens. Exact-title search also returned a short “See also” section instead of the lead. The revised path returns the canonical lead passage and normally answers directly from search evidence; the optimized Apollo run used 9,988 input tokens, a 57.5% reduction.

A later randomized trial added an incorrect term (`IBM`) to its search and confused the spacecraft AGC with the Saturn V computer. The retrieval layer now performs bounded leave-one-term-out strict searches, reciprocal-rank fusion, and canonical title resolution when a long AND query has no exact-title hit. The previously bad query now returns `enwiki:188887` and its lead chunk first.

The model also requested excessive context windows and issued a broad OR query. Agent-facing context sizes are now safely clamped and reported, while unrestricted OR remains available to humans through the CLI/API but is omitted from the MCP schema to avoid common-term scans over 35.8 million chunks.

## Reproduction

```powershell
.\scripts\evaluate-wikipedia-agent.ps1 -ModelId glm-4.7-flash -Unload
```

The versioned suite is `rag/eval/wikipedia-agent-v1.json`. Raw events and reports are retained under `results/rag/agent-e2e/` and intentionally excluded from Git.

This suite is a focused operational gate, not a general measure of answer quality. The next retrieval-quality milestone is semantic/vector retrieval and reranking against the existing non-gating semantic challenge suite.
