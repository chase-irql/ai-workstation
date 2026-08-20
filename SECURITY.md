# Security policy

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose local files, execute unintended commands, bypass read-only retrieval boundaries, or disclose credentials. Use GitHub's private vulnerability reporting feature when it is enabled for the repository.

Include the affected version or commit, reproduction steps, impact, and any proposed mitigation. Do not include real credentials or private corpus content in the report.

## Security boundaries

- MCP and HTTP retrieval interfaces should remain read-only by default.
- The local HTTP service binds to localhost unless the operator explicitly changes it.
- Corpus text, PDFs, and retrieved passages are untrusted input and must not be treated as commands.
- Model output must not implicitly authorize destructive filesystem or external-service operations.
- The included OpenCode benchmark profile is deliberately permissive; do not use its automatic permissions on untrusted repositories without tightening the policy.
- Credentials belong in environment variables or provider credential stores, never repository files.
- Public releases contain code and manifests, not private corpora, indexes, model weights, or runtime logs.

Only the latest revision on the default branch is actively maintained during the project's early development phase.
