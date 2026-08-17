# Phase 1 decisions

## Windows-native first

OpenCode recommends WSL on Windows, but WSL2 cannot currently start on this machine. Native Windows builds of Ollama, Codex, and OpenCode are installed and will be measured first. Enabling firmware virtualization and WSL2 remains a later A/B test, not a prerequisite.

## Context baseline

Both the current Ollama integration guidance for Codex and OpenCode recommend at least a 64K context for coding agents. The first fair harness comparison therefore uses 65,536 tokens. Since context is expensive on a 16 GB GPU, Ollama is configured with Flash Attention and q8_0 KV-cache quantization.

## Model order

1. Devstral Small 2 Q4_K_M (15 GB) establishes the most GPU-friendly coding baseline.
2. Qwen3-Coder 30B-A3B Q4_K_M (19 GB) is the primary specialist candidate.
3. GLM-4.7-Flash Q4_K_M (19 GB) is the general-agent comparison.
4. Nemotron-3-Nano 30B-A3B Q4_K_M (24 GB) is deferred.

The official Ollama Qwen and GLM tags currently provide Q4_K_M, not the Q3_K_M quantizations proposed in the original plan. Using official tags first reduces template/tool-call variables. A custom GGUF/Q3 lane can be added after the official integration baseline.

## Fairness rules

- Same exact Ollama model digest.
- Same 65,536-token context and q8_0 KV cache.
- Same seed commit, prompt, and verification command.
- Fresh isolated Git workspace for every run.
- No web access or cloud fallback.
- Success is determined by verification, not the harness exit code.
- Record wall time, logs, final diff, GPU state, model residency, and versions.
