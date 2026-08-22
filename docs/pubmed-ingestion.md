# PubMed baseline ingestion

The PubMed adapter preserves the complete annual NLM bibliographic baseline without creating a second full uncompressed XML copy. It is designed for a collection large enough to require resumable acquisition, resumable parsing, compressed processed shards, and atomic index publication.

## Data boundary

The registered `pubmed-baseline-2026` generation contains all 1,334 `pubmed26n*.xml.gz` baseline files. Daily update files and full-text PMC articles are separate datasets and are not mixed into this generation.

Each source file is accepted only after its adjacent NLM MD5 matches. The acquisition manifest also records a local SHA-256. Existing complete files and range-resumable partials are reused safely.

PubMed supplies bibliographic records and abstracts where available. It is not a clinical guidance database, and individual abstracts may remain under publisher copyright.

## Run the pipeline

Resume or validate acquisition:

```powershell
.\scripts\acquire-dataset.ps1 -DatasetId pubmed-baseline-2026
```

After `corpora/raw/pubmed/baseline-2026/acquisition-manifest.json` reports `status: validated`, run:

```powershell
.\scripts\run-pubmed-pipeline.ps1
```

The pipeline performs two publication gates:

1. `offline_rag.pubmed` streams each gzip XML source into one documents shard and one chunks shard compressed with Zstandard.
2. `offline_rag.bm25` builds beside the destination, validates counts, foreign keys, FTS rows, and a smoke query, then atomically publishes the SQLite database.

The importer checkpoints after every source file. If Windows restarts or the process is interrupted, rerun the same command; completed source shards are retained. A partially written current shard is never published.

## Published 2026 generation

The completed local generation contains:

- 1,334 checksum-verified publisher archives totaling 54,268,918,978 bytes;
- 39,994,988 documents and 91,890,722 chunks in 33,095,953,327 bytes of compressed processed shards;
- a 232,862,633,984-byte schema-v2 SQLite BM25/FTS5 index.

Run its stable-PMID lexical gate with:

```powershell
.\scripts\evaluate-documentation.ps1 `
  -DatasetId pubmed-baseline-2026 `
  -Suite rag\eval\pubmed-baseline-2026-v1.json
```

The first 10-topic gate achieved Success@1/5/10, MRR@10, and Recall@5/10/50 of 1.0, nDCG@10 of 0.995583, and 394.277 ms mean latency. It is a reproducible retrieval regression test, not a broad assessment of biomedical coverage or clinical correctness.

Run the model-and-tools gate with:

```powershell
.\scripts\evaluate-knowledge-agent.ps1 `
  -Suite rag\eval\pubmed-agent-v8.json `
  -ModelId glm-4.7-flash `
  -Unload
```

The accepted 2026 gate uses three ordinary literature questions covering CRISPR/Cas9, the obese/lean twin gut-microbiome study, and an Alzheimer blood-biomarker review. The recorded GLM trace retrieved the three stable target PMIDs, used the required PubMed URLs, covered every scored abstract-grounded concept, and made no failed MCP calls. Its v8 report passed 3/3 cases. Earlier rubric versions and failed reports remain under the ignored `results/rag/agent-e2e/` tree so evaluation changes do not overwrite history.

When only the deterministic rubric changes, rescore an existing immutable trace without loading a model:

```powershell
.\scripts\evaluate-knowledge-agent.ps1 `
  -Suite rag\eval\pubmed-agent-v8.json `
  -ModelId glm-4.7-flash `
  -ReplayDirectory results\rag\agent-e2e\<recorded-run>
```

Replay copies the raw JSONL events into a new result directory, preserves the original harness exit codes and model token counts, and records `replayed_from` in the report. It does not claim new inference latency. The three-case gate is a focused integration regression, not a broad measure of biomedical answer quality.

## Record model

One PubMed citation becomes one common document with a stable ID of the form `pubmed-baseline-2026:pmid:<PMID>`. Its canonical source URL is the corresponding PubMed record.

The document retains, when present:

- PMID and record version;
- DOI, PMCID, and other publisher identifiers;
- article title, authors, journal, ISSN, volume, issue, and pages;
- publication and NLM revision dates;
- abstract sections and labels;
- languages and publication types;
- MeSH headings, keywords, and indexed chemicals.

Abstract sections become structured chunks. MeSH, keywords, publication types, and chemicals form a separate indexing chunk. Records without an abstract still receive a compact citation-metadata chunk so their titles and identifiers remain searchable.

## Storage and updates

Raw publisher gzip files remain in `corpora/raw/pubmed/`. Processed common records remain compressed in `corpora/processed/pubmed/`; the importer never materializes the entire baseline as uncompressed XML.

Treat each annual baseline as an independent generation. Acquire the new year beside the current one, parse and index it, run the evaluation gate, switch the MCP configuration only after validation, and then archive the older raw generation if desired. Do not merge annual baselines or daily updates by copying XML files into an existing generation.
