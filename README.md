# Local AI Workstation

This open-source repository is the control plane for a private, replaceable-model AI workstation and offline knowledge system. It contains acquisition, ingestion, indexing, retrieval, evaluation, and agent-integration code. Large model files, generated benchmark runs, corpora, and indexes live beside the repository but are intentionally excluded from Git.

The project code is licensed under Apache-2.0. Downloaded corpora, model weights, and derived indexes retain their upstream licenses and are not covered by the project license. See [Data distribution policy](docs/data-distribution-policy.md) before publishing any generated artifact.

The checked-in OpenCode benchmark profile grants tools automatically and is intended only for trusted local repositories and reviewed commands. Tighten `config/harnesses/opencode.json` before using it on untrusted code or corpora.

## Phase 1 status

- Windows-native baseline: Windows 10 Pro 22H2, RTX 5080 16 GB, 64 GB RAM.
- Runtime: Ollama 0.32.14.
- Harnesses: Codex CLI 0.147.0 and OpenCode 1.18.18.
- Fair-comparison context: 65,536 tokens for both harnesses.
- Memory controls: Flash Attention, q8_0 KV cache, one loaded model, one parallel request.
- Installed models: Devstral Small 2 Q4_K_M, Qwen3-Coder 30B-A3B Q4_K_M, and GLM-4.7-Flash Q4_K_M.
- Initial ledger benchmark: OpenCode passed all three pairings; Codex passed Devstral and GLM but failed Qwen after corrupting the edited file. These are single-trial sanity results, not a final ranking.

`D:` is a 1 TB NVMe volume with about 954 GiB usable free space at initialization. The computer has roughly 4 TB of NVMe storage in total, but only this 1 TB volume is currently dedicated to the project.

## Quick start

The automation is currently Windows-first. Create the local Python environment from PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r rag\requirements.txt
```

Then run from this directory:

```powershell
.\scripts\configure-ollama.ps1 -MigrateExistingStore -RestartApp
.\scripts\test-environment.ps1
.\scripts\pull-model.ps1 -ModelId devstral-small-2
.\scripts\smoke-test-model.ps1 -ModelId devstral-small-2
.\scripts\run-benchmark.ps1 -Harness codex -ModelId devstral-small-2 -TaskId ledger-refund
.\scripts\run-benchmark.ps1 -Harness opencode -ModelId devstral-small-2 -TaskId ledger-refund
```

Each benchmark run gets a fresh isolated Git workspace under `results/runs/` and records harness output, verification output, the final diff, timing, and environment metadata.

For development and tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r rag\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest rag\tests -q
```

See `docs/phase-1-results.md` for measurements and caveats.

## Layout

- `benchmarks/`: immutable task definitions and seed repositories.
- `config/`: model registry and harness configuration.
- `docs/`: architecture decisions and machine inventory.
- `scripts/`: setup, diagnostics, model management, and benchmark automation.
- `models/`: Ollama and later GGUF model storage; ignored by Git.
- `results/runs/`: generated benchmark evidence; ignored by Git.
- `corpora/raw/`: downloaded source archives and extracted corpora; ignored by Git.
- `indexes/`: generated BM25/vector indexes; ignored by Git.

Only source code, documentation, versioned manifests, evaluation suites, and tiny synthetic test fixtures belong in this repository. Do not commit raw datasets, extracted source text, vector databases, model weights, credentials, personal documents, or machine-generated result directories.

Do not compare harnesses using different model tags, contexts, prompts, seed commits, or runtime settings. Change one variable at a time.

## Wikipedia dump

The English Wikipedia articles-only multistream dump is stored under `corpora/raw/wikipedia/`. Downloads use BITS for resumability and are verified against Wikimedia's published SHA1 checksums.

```powershell
.\scripts\download-wikipedia.ps1 -DumpDate 20260801
.\scripts\get-wikipedia-download-status.ps1 -DumpDate 20260801
```

The CPU-only extraction and BM25 pilot does not load Ollama or use the GPU:

```powershell
.\scripts\run-wikipedia-pilot.ps1 -MaxArticles 10000
.\scripts\query-wikipedia.ps1 -Query 'Apollo guidance computer'
.\scripts\evaluate-wikipedia.ps1
```

For the complete CPU-only extraction and BM25 build:

```powershell
.\scripts\run-wikipedia-full.ps1
.\scripts\get-wikipedia-full-status.ps1
```

The complete verified index can be searched from PowerShell or served through a local browser/API without loading a model or using the GPU:

```powershell
.\scripts\query-wikipedia.ps1 -Query 'What was the Apollo program?'
.\scripts\start-wikipedia-service.ps1 -Background
.\scripts\get-wikipedia-service-status.ps1
```

Open `http://127.0.0.1:8765/` after the service starts. Stop it with `.\scripts\stop-wikipedia-service.ps1`. The service is read-only and binds only to localhost by default.

Give Codex and OpenCode on-demand access to the same index through local MCP tools:

```powershell
.\scripts\configure-wikipedia-mcp.ps1
```

This does not start an LLM. The MCP process is launched by an agent only when the tools are needed.

Run the model-backed retrieval gate with the default general-agent model from `config/models.json`:

```powershell
.\scripts\evaluate-wikipedia-agent.ps1 -Unload
```

The gate verifies actual MCP calls, stable Wikipedia document IDs, expected answer facts, exact citations, and failed-tool count. `-Unload` releases the model from Ollama afterward.

The multistream extractor uses deterministic compressed shards and block-level resume. Use `.\scripts\run-wikipedia-full.ps1 -Resume` after a reboot or interruption.

See `docs/rag-phase-2-results.md` for the verified-corpus results and `docs/rag-agent-results.md` for the model-and-tool verification.

## Documentation corpora

The corpus-neutral documentation path now imports HTML, Markdown, reStructuredText, AsciiDoc, man/roff, RFC text, and plain text into the same common record model and atomic SQLite FTS5/BM25 baseline used by Wikipedia. Python 3.14.7, Git 2.55.0, Linux man-pages 6.18, and the 2026-08-19 RFC Editor text snapshot are acquired, parsed, indexed, and evaluated. A separate table-aware importer has also published the complete 2026-08-19 IANA protocol-registry snapshot: 4,256 registry documents and 114,590 searchable chunks.

```powershell
.\scripts\validate-dataset-registry.ps1
.\scripts\query-documentation.ps1 -DatasetId python-3.14-docs -Query 'pathlib glob recursive patterns'
.\scripts\evaluate-documentation.ps1 -DatasetId python-3.14-docs -Suite rag\eval\python-docs-pilot-v1.json
.\scripts\query-documentation.ps1 -DatasetId rfc-editor-text -Query 'TLS 1.3 key schedule'
.\scripts\query-documentation.ps1 -DatasetId iana-protocol-registries -Query 'https tcp port'
```

See `docs/documentation-corpus-ingestion.md` for acquisition, rebuild, safety, parser, storage, and update details. These commands are CPU-only and do not load a local model. Embedding and hybrid rollout for the new corpora is staged separately in `docs/corpus-semantic-roadmap.md`.

Chunk-level semantic generations can be built independently after the BM25 gate:

```powershell
.\scripts\run-corpus-semantic.ps1 -DatasetId python-3.14-docs
.\scripts\get-corpus-semantic-status.ps1
.\scripts\evaluate-corpus-semantic.ps1 -DatasetId python-3.14-docs -Suite rag\eval\python-docs-semantic-v1.json
```

Python, Git, and Linux man-pages now have published semantic generations covering all 26,948 chunks. RFC Editor adds another verified 348,831 chunk vectors across 9,822 documents. Exact identifiers remain BM25-first; natural-language paraphrases use hybrid retrieval through the unified MCP.

## Unified offline knowledge tools

OpenCode can search Wikipedia, Python, Git, Linux man-pages, RFCs, and IANA protocol registries through one read-only MCP server while every corpus remains independently replaceable:

```powershell
.\scripts\configure-knowledge-mcp.ps1 -Harness opencode
.\scripts\start-opencode.ps1
```

To run the same local Ollama models through Codex without changing the normal global Codex model, use the isolated launcher:

```powershell
.\scripts\start-codex.ps1
```

Every launch prompts for the working directory, then shows a terminal selector containing the non-embedding models currently installed in Ollama. Use the arrow keys and Enter to select a model, or Escape to cancel. The temporary Codex home is scoped to the launched process; plain `codex` continues to use the personal global configuration.

The unified tools are `search_knowledge`, `retrieve_knowledge_context`, `retrieve_knowledge_document`, and `knowledge_index_status`. The existing Wikipedia-specific MCP tools remain configured for compatibility. See `docs/unified-knowledge-mcp.md` for corpus filters, CPU-only BM25 selection, ranking behavior, fallback behavior, and example prompts.
