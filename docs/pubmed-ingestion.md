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
