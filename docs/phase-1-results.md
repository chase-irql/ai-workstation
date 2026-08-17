# Phase 1 results

## Devstral Small 2 Q4_K_M smoke test

The official Ollama model digest `24277f07f62d...` loaded successfully with tool and vision capabilities at a requested 65,536-token context.

| Measurement | Result |
|---|---:|
| Runtime footprint | 20.79 GB |
| VRAM-resident portion | 13.58 GB |
| GPU memory after load | 15,834 / 16,303 MiB |
| Prompt evaluation | about 31 tokens/s |
| Generation | about 3 tokens/s |
| Cold load | about 15.2 seconds |

The model is not fully GPU-resident at 64K on this desktop workload. Closing GPU-heavy background applications may improve residency slightly, but the current Q4 dense model still requires material system-RAM participation.

## Harness sanity task

Task: diagnose a signed-total bug, edit one Python function, and pass two tests.

| Harness/configuration | Result | Wall time | Observed behavior |
|---|---:|---:|---|
| OpenCode 1.18.18 | Pass | 124.9 s | Delegated to its general subagent, made the minimal fix, passed tests |
| Codex 0.147.0, isolated 64K catalog | Pass | 89.7 s | Inspected files, reproduced failure, made the minimal fix, passed tests |
| Codex initial built-in Ollama lane | Fail | 264.0 s | Catalog schema fallback, 242k input tokens, rejected commands, no edit |

The initial Codex failure is retained as integration evidence but is not a fair score for the harness. Ollama's generated profile showed that Codex needs an explicit local model catalog. The benchmark now uses an isolated project-owned catalog with the real 65,536-token limit plus automatic workspace approval.

This task only validates the machinery. It is far too small to decide the overall harness winner; the remaining multi-file, refactor, failing-test, and vague-issue tasks are still required.
