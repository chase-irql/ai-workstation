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

## Full Wikipedia build

The full build extracts all main-namespace articles and then creates the complete BM25 database. It does not load an LLM or require the GPU.

```powershell
.\scripts\run-wikipedia-full.ps1
.\scripts\get-wikipedia-full-status.ps1
```

The full corpus is written to `corpora/processed/wikipedia/enwiki-20260801/full/`; the completed index will be `indexes/wikipedia/enwiki-20260801-full.sqlite3`.
Extraction writes a durable checkpoint every 1,000 articles. After an interruption, continue with `.\scripts\run-wikipedia-full.ps1 -Resume`.
