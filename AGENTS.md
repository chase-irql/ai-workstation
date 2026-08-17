# Repository instructions

- Keep the system model- and harness-independent. Model IDs belong in `config/models.json`, not scattered through scripts.
- Treat benchmark task prompts and seed commits as immutable after a result has been recorded. Create a new task version instead of silently editing an old one.
- Keep new large downloads under `D:\ai-workstation`; never place corpora, indexes, or model weights in Git.
- Prefer Windows-native PowerShell while WSL2 is unavailable.
- Never store credentials in this repository. Use environment variables or provider credential stores.
- Benchmark runs must use fresh isolated workspaces and must retain verification output and the final diff.
- Use deterministic test commands where possible. Do not score a run as successful only because the harness exited with code zero.
