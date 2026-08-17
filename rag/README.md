# Offline RAG foundation

This package provides the CPU-only foundation for the local knowledge system:

- streaming MediaWiki XML extraction;
- structure-aware, provenance-preserving chunks;
- SQLite FTS5/BM25 indexing and search;
- source-backed result records suitable for a later MCP tool.

Vector embeddings and LLM generation are deliberately separate stages. The Wikipedia pilot can be parsed, indexed, and searched without Ollama or GPU use.

## Pilot commands

From `D:\ai-workstation`:

```powershell
.\scripts\run-wikipedia-pilot.ps1 -MaxArticles 10000
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance computer'
```

Generated documents live under `corpora/processed/wikipedia/`; search indexes live under `indexes/wikipedia/`. Both are excluded from Git and can be rebuilt from the verified raw dump.
