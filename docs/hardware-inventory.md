# Hardware and software inventory

Captured on 2026-08-17.

| Component | Observed value |
|---|---|
| OS | Windows 10 Pro 22H2, build 19045, 64-bit |
| CPU | Intel Core i7-14700KF, 20 cores / 28 logical processors |
| GPU | NVIDIA GeForce RTX 5080, 16,303 MiB VRAM |
| NVIDIA driver | 610.62; CUDA UMD 13.3 |
| RAM | 63.8 GiB total |
| D: | 1 TB NVMe, about 953.7 GiB free at initialization |
| Other NVMe | One additional 1 TB SSD and one 2 TB Crucial T710 |
| Ollama | 0.32.14, Windows-native |
| Codex CLI | 0.147.0 |
| OpenCode | 1.18.18 |
| Git | 2.54.0.windows.1 |
| Node.js | 26.3.1 |
| Python | 3.14.6 |
| WSL | Installed, but WSL2 cannot start because virtualization is disabled; Ubuntu is WSL1 |

At inventory time, desktop applications consumed about 2.3 GiB of VRAM. Benchmark reports must record available VRAM because background GPU use materially changes offload behavior.

