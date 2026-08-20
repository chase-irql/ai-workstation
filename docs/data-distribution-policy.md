# Data distribution policy

This repository distributes the software needed to acquire, validate, parse, index, evaluate, and query offline knowledge. It does not distribute the local knowledge library itself.

## Included in Git

- source code and PowerShell automation;
- corpus schemas and corpus-neutral record definitions;
- source URLs, release identifiers, expected sizes, checksums, and license metadata;
- versioned evaluation suites containing queries and stable identifiers;
- tiny synthetic fixtures created specifically for automated tests;
- aggregate measurements and documentation that do not reproduce substantial source text.

## Excluded from Git

- raw or extracted corpora;
- PDFs, books, manuals, Wikipedia dumps, Stack Exchange dumps, and package repositories;
- SQLite/FTS, FAISS, vector, and reranker indexes;
- model weights, Ollama stores, GGUF, ONNX, and safetensors files;
- generated evaluation output and runtime logs;
- personal documents, credentials, API tokens, and machine-specific caches.

The exclusions are enforced in `.gitignore`, but contributors must still inspect staged files before every push.

## Why datasets and indexes are separate

Corpora have different licenses, attribution rules, update schedules, and redistribution restrictions. Some generated indexes contain recoverable or verbatim source text and may be derivative database artifacts. A permissive license on this project's code cannot relicense that content. Large artifacts also do not belong in ordinary Git history.

Users should acquire each corpus from its official publisher with the scripts and pinned metadata in `config/datasets.json`. This keeps provenance and checksums reproducible without making this repository a mirror of third-party data.

## Optional artifact releases

A prebuilt corpus or index may be released separately only after a corpus-specific review records:

1. the exact upstream release and source URL;
2. permission to redistribute both source material and the proposed derived format;
3. required attribution and notices;
4. checksums, schema version, and build identity;
5. update and takedown procedures;
6. confirmation that no personal or proprietary documents are present.

Approved large artifacts should use dedicated object storage or a separate release mechanism, never the main Git repository. Absence from Git does not imply that an artifact is safe or licensed for redistribution.

## Project versus corpus licensing

The repository's Apache-2.0 license applies to original project code and documentation. Every downloaded corpus and model remains governed by its own license or terms. The license fields in `config/datasets.json` are operational metadata, not legal advice; verify upstream terms before redistribution.
