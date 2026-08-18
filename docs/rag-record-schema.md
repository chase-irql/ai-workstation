# Corpus-neutral retrieval records

Schema version 1 separates source documents, repeated chunk occurrences, and reusable normalized content. JSONL remains the interchange format; corpus importers remain independent of model providers and RAG frameworks.

## Documents

- `document_id`: stable corpus-qualified identifier.
- `corpus`: stable corpus name such as `wikipedia-en` or `manuals`.
- `title`: display title.
- `source_url`: source locator when available.
- `source_version`: dump, publication, product, or documentation version.
- `source_timestamp`: source revision/publication timestamp, not ingestion time.
- `license`: SPDX identifier or documented source-specific value when known.
- `content_hash`: optional whole-document content hash.
- `attributes`: corpus-specific metadata.

## Chunks

- `chunk_instance_id`: stable identity for this occurrence in this document/version.
- `content_id`: `sha256:` plus the SHA-256 of NFC-normalized UTF-8 text with normalized newlines.
- `document_id`: owning document.
- `parent_chunk_id`: optional hierarchical parent instance.
- `ordinal`: zero-based order within the document.
- `heading_path`: ordered structural headings.
- `text`: normalized display/retrieval text.
- `character_count`: Python Unicode character count.
- `token_count`: optional count from a named tokenizer; null when unavailable.
- `previous_chunk_id` and `next_chunk_id`: neighboring instances in the document.
- `attributes`: corpus-specific metadata such as page, revision, or section indexes.

Version-1 Wikipedia `document_id` and `chunk_id` values are retained. Its existing content hash becomes the reusable content ID, while revision and section fields move into attributes. The adapter buffers only one document's chunks to assign ordinals and neighbor links.

