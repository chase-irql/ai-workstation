# Local AI Workstation

This repository is the control plane for a private, replaceable-model AI workstation. Large model files, generated benchmark runs, corpora, and indexes live beside the repository under `D:\ai-workstation`, but are intentionally excluded from Git.

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

Run PowerShell from this directory:

```powershell
.\scripts\configure-ollama.ps1 -MigrateExistingStore -RestartApp
.\scripts\test-environment.ps1
.\scripts\pull-model.ps1 -ModelId devstral-small-2
.\scripts\smoke-test-model.ps1 -ModelId devstral-small-2
.\scripts\run-benchmark.ps1 -Harness codex -ModelId devstral-small-2 -TaskId ledger-refund
.\scripts\run-benchmark.ps1 -Harness opencode -ModelId devstral-small-2 -TaskId ledger-refund
```

Each benchmark run gets a fresh isolated Git workspace under `results/runs/` and records harness output, verification output, the final diff, timing, and environment metadata.

See `docs/phase-1-results.md` for measurements and caveats.

## Layout

- `benchmarks/`: immutable task definitions and seed repositories.
- `config/`: model registry and harness configuration.
- `docs/`: architecture decisions and machine inventory.
- `scripts/`: setup, diagnostics, model management, and benchmark automation.
- `models/`: Ollama and later GGUF model storage; ignored by Git.
- `results/runs/`: generated benchmark evidence; ignored by Git.
- `corpora/raw/`: future source documents; ignored by Git.
- `indexes/`: future BM25/vector indexes; ignored by Git.

Do not compare harnesses using different model tags, contexts, prompts, seed commits, or runtime settings. Change one variable at a time.
