# PDF manual ingestion

The PDF adapter is for manuals, handbooks, datasheets, and reports whose page layout is part of their citation identity. It produces the same common document/chunk records and atomic SQLite FTS5 index used by the other corpora, but it does not flatten pages into an anonymous text stream.

## Preserved structure

Each PDF is one common document. The document records its relative path, SHA-256, PDF metadata, source version, license, canonical URL, page counts, and text-layer coverage. Every chunk belongs to exactly one page and records:

- one-based physical page number;
- printed PDF page label where available;
- active bookmark/outline hierarchy where available;
- its exact occurrence ID and reusable content ID;
- previous/next chunk links;
- section and chunk ordinals.

Search citations therefore identify both the source document and a `Page …` heading. Oversized page text is split deterministically, but chunks never cross page boundaries.

## OCR safety gate

Version 1 extracts existing PDF text layers with `pypdf`; it does not run OCR. Pages with images but no text are counted as image-only, while truly empty pages are counted separately. The import fails atomically when there is no searchable text or when the searchable ratio among text/image pages is below `--min-searchable-ratio` (default `0.5`). No partial corpus is published after this failure.

This conservative behavior prevents a scanned service manual from appearing successfully indexed when its diagrams and instructions are actually invisible. OCR should be a later, explicit preprocessing stage that preserves page coordinates, rendered-page QA, OCR engine/version, and original PDFs.

## Registry-driven pipeline

Add the dataset to `config/datasets.json` before ingestion. Record the official source, release, license, acquisition URL/checksum, storage ceilings, and paths. After acquiring and validating the PDFs, run:

```powershell
.\scripts\run-pdf-manual-pipeline.ps1 -DatasetId <dataset-id>
```

Useful controls:

```powershell
# Bound a pilot. The output is explicitly incomplete and the BM25 build is marked accordingly.
.\scripts\run-pdf-manual-pipeline.ps1 -DatasetId <dataset-id> -MaxFiles 5

# Replace only a recognized prior importer output and atomically replace the index after success.
.\scripts\run-pdf-manual-pipeline.ps1 -DatasetId <dataset-id> -Force
```

The script defaults to the registry `paths.raw` location, but `-Source` can point to a single PDF or a directory tree. `-Force` never replaces an output directory containing unrelated files.

## Evaluation and publication

Before changing a dataset status to `evaluated`:

1. inspect extraction statistics and the text/image/blank page counts;
2. review a sample of extracted pages against the original PDF;
3. verify the BM25 database and input checksums;
4. create a stable-ID evaluation suite with questions that target exact errors, procedures, part numbers, and conceptual explanations;
5. inspect citations for the expected title and page;
6. configure the unified MCP only after the gate passes.

Semantic embeddings are not automatic. Exact model numbers, error codes, and part numbers often favor BM25. Add chunk embeddings only when a judged paraphrase suite demonstrates a retrieval gap.

## Validated pilot

`faa-amt-general-2023` is the first real corpus through this adapter. Its official 92,539,602-byte FAA-H-8083-30B PDF contains 677 pages; 676 have text and one cover is image-only. The published generation contains 1,837 page-bounded chunks and a 9,388,032-byte verified BM25 database. A 14-topic lexical coverage gate passes every cutoff, and manual citation inspection confirms page-aware results for electricity, nondestructive inspection, tools, corrosion, drawings, mathematics, fire safety, weight and balance, and fluid lines.

The pilot revealed rotated text in diagrams and tables. The importer keeps this text searchable, accepting locally degraded spacing instead of the extraction library's default behavior of dropping it. Front-matter matches remain searchable but are ranked after matching body evidence.

## Current limitations

- No OCR or handwriting recognition.
- No table reconstruction or figure-caption extraction beyond text already present in the PDF layer.
- Bookmark hierarchy is best effort because malformed PDF outlines are common.
- Physical page numbers and embedded page labels are preserved, but URLs remain document-level; citations carry the page label.
- Password-protected PDFs are rejected. PDFs encrypted with an empty password are accepted when `pypdf` can decrypt them.
