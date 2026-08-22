# Qwen3.5 4B Abliterated BF16

## Installation

- Source: `wangzhang/Qwen3.5-4B-abliterated`
- Source revision: `3bcc7a546b609f8d4f7344b52a5dda1b8298cf7d`
- Source weight SHA-256: `65c20d5e13c302c58ab8cb32be8834b66951cd7cac5be8ebadaf69f47596240e`
- Ollama name: `qwen3.5-4b-abliterated:bf16`
- Model size: 4.2B parameters, 8.42 GB GGUF
- GGUF SHA-256: `18144b3c2ea7f5d7bd2b459be355c3682699b62b99f54d2d805af1250eeb3094`
- Conversion tool: `ggml-org/llama.cpp` revision `b21e4de`

The original repository publishes BF16 Safetensors. Ollama's experimental native-Safetensors import was not loadable by the normal Windows CUDA server, so the source was converted locally to a standard GGUF while retaining BF16 model tensors:

```powershell
.\.venv\Scripts\python.exe runtime\llama.cpp-converter\convert_hf_to_gguf.py `
  models\huggingface\wangzhang\Qwen3.5-4B-abliterated `
  --outfile models\huggingface\wangzhang\Qwen3.5-4B-abliterated\Qwen3.5-4B-abliterated.BF16.gguf `
  --outtype bf16 `
  --no-mtp
```

## Runtime profile

| Setting | Value |
| --- | ---: |
| Model precision | BF16 |
| Context | 32,768 tokens |
| GPU offload | All layers |
| K/V cache | FP16 |
| Flash Attention | Enabled |
| Thinking | Enabled |
| Temperature | 0.6 |
| Top-p | 0.95 |
| Top-k | 20 |
| Maximum output | 8,192 tokens |

K/V cache precision is an Ollama server setting, not a per-request setting. Start Ollama with `OLLAMA_KV_CACHE_TYPE=f16` when this exact profile is required. The repository-wide default remains `q8_0` because the larger local models need its lower VRAM usage.

## Verification on RTX 5080 16 GB

Verified on 2026-08-22 with Ollama 0.32.15:

- Ollama reported the model as GGUF `BF16`, family `qwen35`, with 4.2B parameters.
- The live runner used `-c 32768`, `--cache-type-k f16`, `--cache-type-v f16`, and `--flash-attn on`.
- Ollama reported `9,741,218,610` bytes allocated entirely in VRAM (`size_vram == size`).
- Total GPU use during the loaded test was 11,532 MiB, including Windows desktop applications, leaving 4,446 MiB free.
- A reasoning calculation returned the correct final answer. Thinking output was present, confirming thinking mode.
- A constrained tool-use prompt emitted exactly one valid `lookup_code({"code":"RFC 9110"})` call.
- A 28,039-token prompt recalled an exact marker successfully at 6,616 prompt tokens/second.
- Generation measured about 77 tokens/second in the two smoke tests.

The model spent 5,644 reasoning tokens on a trivial arithmetic prompt. This confirms that thinking works, but it can be excessively verbose and inefficient on easy tasks. Use thinking selectively when latency or token economy matters.

## Safety note

This checkpoint is explicitly abliterated. Its safety alignment has been deliberately weakened, so it should not be treated as a trusted authority for medical, legal, security, or destructive operational decisions. Ground consequential answers in authoritative retrieved sources and retain tool permissions and human review.
