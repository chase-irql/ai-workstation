# Contributing

Contributions to ingestion safety, corpus-neutral records, retrieval quality, evaluation, documentation, and provider-independent agent tooling are welcome.

## Before opening a change

1. Read `AGENTS.md` and preserve recorded benchmark prompts and seed commits.
2. Keep models, corpora, indexes, generated results, and credentials out of Git.
3. Add or update focused tests using tiny synthetic fixtures.
4. Preserve source provenance, stable identifiers, licenses, versions, and citations.
5. Keep the core independent of a specific LLM, harness, vector service, or cloud provider.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest rag\tests -q
.\scripts\validate-dataset-registry.ps1
git diff --check
```

Corpus additions should begin with a manifest entry and a small parser/indexing pilot. Do not attach or commit a real corpus sample unless its redistribution terms have been reviewed and the sample is genuinely necessary.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the right to submit it.
