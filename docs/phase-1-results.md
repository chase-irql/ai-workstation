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

## Qwen3-Coder 30B-A3B Q4_K_M

The official Ollama model digest `06c1097efce0...` also loaded at 65,536 tokens with tool capability.

| Measurement | Result |
|---|---:|
| Runtime footprint | 22.34 GB |
| VRAM-resident portion | 14.61 GB |
| GPU memory after load | 15,595 / 16,303 MiB |
| Short-response generation | about 64.5 tokens/s |
| Cold load | about 10.4 seconds |

The short smoke prompt includes initialization effects, so it is not a reliable prompt-ingestion benchmark. The generation result nevertheless confirms the practical benefit of the 3.3B-active MoE design: despite greater total storage and RAM offload, generation was dramatically faster than dense Devstral.

On the same ledger task:

| Harness | Result | Wall time | Tool calls observed | Input tokens observed |
|---|---:|---:|---:|---:|
| OpenCode 1.18.18 | Pass | 81.4 s | 6 parent-session calls | 74,939 parent-session tokens |
| Codex 0.147.0 | Fail | 52.0 s | 11 | 153,907 |

Codex identified the correct one-line change but used a whole-file PowerShell rewrite that corrupted the Python docstring, leaving a syntax error. OpenCode made the one-line edit and passed the tests. This is one trial, not a stable ranking, but it demonstrates why agent-tool reliability must be measured separately from inference speed.

## GLM-4.7-Flash Q4_K_M

The official Ollama model digest `4475827791a2...` loaded at 65,536 tokens with tool and thinking capabilities.

| Measurement | Result |
|---|---:|
| Runtime footprint | 21.25 GB |
| VRAM-resident portion | 14.56 GB |
| GPU memory after load | 15,781 / 16,303 MiB |
| Short-response generation | about 59.8 tokens/s |
| Cold load | about 9.2 seconds |

The first OpenCode attempt was invalidated after the model discovered a globally installed writing skill unrelated to the benchmark. OpenCode was then isolated from global configuration, skills, external-directory access, and network tools, and the run was repeated.

| Harness/configuration | Result | Wall time | Tool calls observed | Failed calls | Input tokens observed |
|---|---:|---:|---:|---:|---:|
| OpenCode 1.18.18, isolated rerun | Pass | 72.7 s | 12 | 1 | 97,355 |
| Codex 0.147.0, isolated catalog | Pass | 164.0 s | 20 | 5 | 149,323 |
| OpenCode contaminated first run | Invalid | 38.8 s | 12 | 1 | 50,715 |

Both valid runs produced the correct fix and passed the tests. OpenCode made the minimal one-line edit. Codex reached the correct result but took a circuitous path and left an untracked temporary script in the workspace.

## Preliminary cross-model summary

| Model | Codex | OpenCode | Faster passing run |
|---|---:|---:|---:|
| Devstral Small 2 Q4_K_M | Pass, 89.7 s | Pass, 124.9 s | Codex |
| Qwen3-Coder 30B-A3B Q4_K_M | Fail, 52.0 s | Pass, 81.4 s | OpenCode |
| GLM-4.7-Flash Q4_K_M | Pass, 164.0 s | Pass, 72.7 s | OpenCode |

This is a plumbing and behavior check, not a model leaderboard. The sample size is one small bug per pairing, and the Devstral and Qwen OpenCode runs predate the stricter global-skill isolation (neither log shows the contamination observed with GLM). A defensible winner requires the remaining task classes, repeated trials, and fully isolated reruns.

The useful hardware result is already clear: all three official Q4 models run at 65,536 tokens, but none is fully resident in 16 GB VRAM. The two sparse MoE models generate much faster than dense Devstral despite their larger total weight footprints.
