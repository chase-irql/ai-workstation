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

Version 1 extracts existing PDF text layers with `pypdf`; it does not run OCR. Pages with images but no text are counted as image-only, while truly empty pages are counted separately. The import also records per-document and aggregate counts for pages where `pypdf` reports uninterpretable fonts or rotated text. Those warnings identify targeted visual/OCR review work without flooding a multi-volume import log. The import fails atomically when there is no searchable text or when the searchable ratio among text/image pages is below `--min-searchable-ratio` (default `0.5`). No partial corpus is published after this failure.

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

The script defaults to the registry `paths.raw` location. For an `http-file-set` or `http-catalog-file-set`, it automatically uses that acquisition method's publication-ready `files/` payload root so stable document paths and `source_url_template` values do not acquire an internal storage prefix. `-Source` can point to a single PDF or a directory tree. `-Force` never replaces an output directory containing unrelated files.

When a publisher's embedded PDF title is wrong, add a reviewed JSON mapping of relative PDF paths to exact titles and reference it as `ingestion.title_overrides` in the dataset registry. The importer validates every override against a source file, retains the original embedded title as `pdf_title`, marks the document `title_overridden`, and binds a deterministic override-map digest into the corpus manifest. This is for correcting provenance defects, not casually rewriting publisher titles.

For a publisher-maintained HTML file catalog, `http-catalog-file-set` can discover a tightly bounded linked set without committing hundreds of URLs. The registry must constrain the HTTPS asset prefix, anchored relative-path pattern, expected asset count, individual and total byte ranges, concurrency, exclusions, and optional magic bytes. Acquisition stores and hashes the exact catalog snapshot, refuses path traversal, case collisions, conflicting duplicates, missing declared exclusions, and stale extra files, and hashes every downloaded asset. When `collection_titles` and `ingestion.title_overrides_from_acquisition` are set, visible publisher link labels become deterministic titles and their map digest is bound into the processed-corpus manifest.

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

The second validated corpus is the complete 22-volume DOE Fundamentals archive. It exercises bounded multi-file acquisition, file-set source paths, reviewed title overrides, and structured extraction-warning counts. Across 2,842 pages, 2,692 have searchable text, 6 are image-only, and 144 are blank; 108 pages report legacy uninterpretable fonts and one reports rotated text. The resulting 5,533 chunks occupy a 25,423,872-byte verified BM25 database. Its 59-topic inter-volume gate has Success@1/5/10, Recall@5/10/50, and MRR@10 of `1.0`, with nDCG@10 `0.999418`. Because these handbooks are archived/canceled, citations must not present them as current DOE policy or current safety requirements.

FAA-H-8083-31B Airframe and FAA-H-8083-32B Powerplant complete the AMT handbook trilogy. The two 2023 PDFs contain 1,552 pages; 1,550 are searchable and two covers are image-only. The importer records 183 rotated-text pages and no uninterpretable-font pages. Their 3,498 chunks produce a 19,853,312-byte verified index, and a 47-topic Airframe/Powerplant gate passes every configured metric at `1.0`. The handbooks themselves state that generalized material does not replace regulations or manufacturer instructions.

## Current limitations

- No OCR or handwriting recognition.
- No table reconstruction or figure-caption extraction beyond text already present in the PDF layer.
- Bookmark hierarchy is best effort because malformed PDF outlines are common.
- Physical page numbers and embedded page labels are preserved, but URLs remain document-level; citations carry the page label.
- Password-protected PDFs are rejected. PDFs encrypted with an empty password are accepted when `pypdf` can decrypt them.
