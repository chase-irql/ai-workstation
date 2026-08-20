# OpenStax textbook ingestion

The OpenStax adapter imports official CollXML collection manifests and referenced CNXML modules into the corpus-neutral record schema. It does not scrape rendered web pages, execute source content, or flatten an entire book into anonymous text.

## Current corpora

`openstax-calculus` contains Calculus Volumes 1–3 from official repository commit `8dbc2ce19e804924b2517b89ac72ee45be949d15` (2026-07-15). The snapshot is licensed CC BY-NC-SA 4.0. Repository and collection notices remain with the raw archive, and every indexed document carries its book license and immutable source URL.

The downloaded archive is 134,792,906 bytes with locally measured SHA-256 `c3f589d2b20f8837f6faf8c872ea5f0702e8761097c47ab2d45889145da0b6c5`. GitHub did not publish an adjacent digest and the commit is unsigned, so this is local integrity evidence rather than publisher authentication.

Safe extraction produced 2,084 files totaling 217,389,281 bytes. The collection manifests reference 163 module occurrences. Thirty shared modules occur in adjacent volumes, so the importer publishes 133 unique documents while retaining every book, chapter, and ordinal occurrence in `book_occurrences`.

`openstax-university-physics` contains University Physics Volumes 1–3 from official repository commit `d0ed34a5851119a42e3d972dfc0ff49e4663977c` (2026-06-11). Its 180,736,830-byte archive has locally measured SHA-256 `42c5e22b21fe50ea9897910cc7370b6c57f21a0ef99af32a29b1cc7647598c7d` and safely expands to 2,311 files totaling 250,916,936 bytes. The repository and all three collection manifests state CC BY-NC-SA 4.0. Sixteen shared modules reduce 338 ordered occurrences to 322 unique indexed documents.

`openstax-chemistry` contains Chemistry 2e and Chemistry: Atoms First 2e from official repository commit `3be4b60ff501f29a445f0cacf003e5f5cc16244d` (2026-07-08). Its 279,761,314-byte archive has locally measured SHA-256 `59b329660c5c06e12c86301d5a631ba5fd2a04c9eb122c68d384cf42406233af` and safely expands to 1,731 files totaling 340,181,560 bytes. Both 149-module collections state CC BY-NC-SA 4.0. Their 122 shared module IDs reduce 298 ordered occurrences to 176 unique documents while preserving both curricular sequences.

`openstax-biology` contains Biology 2e, Biology for AP Courses, and Concepts of Biology from official repository commit `63f8b6f8d129dd1582989bb755011e9a6d523471` (2026-07-22). Its 687,639,648-byte archive has locally measured SHA-256 `20ce209a097b576a3121eb98f7e656fd04e4d91e8895139bb9568e25a0f0c33d` and safely expands to 3,043 files totaling 749,160,433 bytes. All three collections state CC BY-NC-SA 4.0. They reference 575 modules but share only one literal module ID, resulting in 574 stable documents. Similar curriculum pages with different module IDs are deliberately not merged; content IDs remain available for downstream cache and evidence deduplication.

`openstax-anatomy-physiology` contains Anatomy and Physiology 2e from official repository commit `716383a4c6c16037b14d75a156c65145e75e895e` (2026-06-12). Its 452,199,473-byte archive has locally measured SHA-256 `e53cc279a599c751f65bdbb6dbb5b0b84c36d47c27d3e32cdc6032bfcb9d38e4` and safely expands to 1,153 files totaling 538,916,603 bytes. Its one 198-module collection states CC BY-NC-SA 4.0. Treat this as dated educational foundation material, not current clinical guidance or medical advice.

`openstax-foundational-algebra` contains Prealgebra 2e, Elementary Algebra 2e, and Intermediate Algebra 2e from official repository commit `38cae454e644abf9f0a623e876994553881597c9` (2026-06-29). Its 527,599,772-byte archive has locally measured SHA-256 `46666e6001e2948ad18888a98420bb5a5b2ed21bbd99426b202963e29ab6669d` and safely expands to 13,738 files totaling 956,565,492 bytes with no links. The extractor portably encoded 13,447 Windows-hostile source paths while preserving reversible names. All three collection manifests state CC BY-NC-SA 4.0. Their 240 ordered module occurrences have distinct stable IDs.

`openstax-college-algebra` contains Algebra and Trigonometry 2e, College Algebra 2e, College Algebra Corequisite Support 2e, and Precalculus 2e from official repository commit `789b54099106b071d1d32bfcee454fed72eb4768` (2026-06-12). Its 167,165,865-byte archive has locally measured SHA-256 `c449330830d48ec223a0a7557dcc07f4ae27187e4e626bec791396853b830b2d` and safely expands to 3,202 files totaling 263,911,946 bytes with no links. All four collection manifests state CC BY-NC-SA 4.0. The 319 ordered occurrences reuse modules heavily, yielding 138 stable documents while retaining all book and chapter placements in provenance.

`openstax-introductory-statistics` contains Introductory Statistics 2e and Introductory Business Statistics 2e from official repository commit `1f6a35825395bb4aa2834cf1eca37512655f920c` (2026-07-07). Its 69,074,097-byte archive has locally measured SHA-256 `3ecc98e6641bef622c48e5f031fda94f0cc3381201c46265f66ff016ef4d324d` and safely expands to 1,546 files totaling 100,079,098 bytes with no links. Both collection manifests state CC BY-NC-SA 4.0. Their 179 module occurrences have distinct stable IDs.

`openstax-microbiology` contains Microbiology from official repository commit `633850257fbd3ccf6187b9428c55e80b69236382` (2026-07-08). Its 329,184,733-byte archive has locally measured SHA-256 `ba89936e92a84cc964c66df73b805ac8a0a9dfb23057ad57ca40097625cf8ab8` and safely expands to 1,047 files totaling 362,279,562 bytes with no links. Its 159-module collection states CC BY-NC-SA 4.0. Treat the infectious-disease and antimicrobial material as dated educational foundation, not current clinical guidance or medical advice.

## Structure retained

The adapter preserves:

- book, chapter, nested collection, and module order;
- stable module IDs and immutable source URLs;
- section hierarchy, examples, exercises, problems, solutions, definitions, and rules;
- code, notes, lists, tables, figure alternative text, and captions;
- deterministic searchable text for common MathML fractions, powers, subscripts, and roots;
- neighboring chunk links, reusable content IDs, and occurrence-specific chunk IDs;
- per-book license text, source hashes, and module UUIDs.

Media remains in the raw snapshot for diagrams and visual inspection but is not inserted into FTS as binary content. Mathematical rendering is intended for retrieval, not lossless round-tripping or typesetting.

## Rebuild and update

Add or update the pinned commit, acquisition URL, size bounds, content subdirectory, release label, and immutable source URL template in `config/datasets.json` before downloading a new snapshot. Acquire it with the repository's bounded archive workflow and validate the recorded archive hash and safe-extraction report.

Then run:

```powershell
.\scripts\run-openstax-pilot.ps1 `
  -DatasetId openstax-calculus `
  -SourceRoot D:\ai-workstation\corpora\raw\textbooks\openstax-calculus `
  -Force

.\scripts\evaluate-documentation.ps1 `
  -DatasetId openstax-calculus `
  -Suite rag\eval\openstax-calculus-v1.json
```

`-Force` only replaces a recognized importer output directory and an explicitly authorized target index. Both replacements are built and validated before publication. Omit `-Force` for the first build; existing outputs are otherwise protected.

Verify independently:

```powershell
$env:PYTHONPATH = 'D:\ai-workstation\rag\src'
.\.venv\Scripts\python.exe -m offline_rag.verify `
  --database indexes\textbooks\openstax-calculus.sqlite3 `
  --input corpora\processed\textbooks\openstax-calculus `
  --smoke-query 'fundamental theorem calculus'
```

Never overwrite the old raw snapshot during acquisition. Download and validate a versioned replacement first, build processed records and indexes atomically, compare the stable-ID suite, and only then update the active registry entry. Keep old raw snapshots until the new build is accepted or storage policy explicitly retires them.

## Current result and limitations

The current index has 133 documents, 11,807 chunks, 11,807 FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 17,432,576 bytes. The 41-case lexical suite has Success@1/5/10, Recall@5/10/50, MRR@10, and nDCG@10 of 1.0.

The University Physics index has 322 documents, 8,870 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 21,135,360 bytes. The 46-case lexical suite likewise has every reported rank metric at 1.0.

The Chemistry index has 176 documents, 4,499 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 12,296,192 bytes. The 46-case lexical suite has every reported rank metric at 1.0.

The Biology index has 574 documents, 10,795 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 30,928,896 bytes. The 52-case lexical suite has every reported rank metric at 1.0.

The Anatomy and Physiology index has 198 documents, 4,590 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 12,288,000 bytes. The 42-case lexical suite has every reported rank metric at 1.0.

The foundational-algebra index has 240 documents, 33,138 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 42,508,288 bytes. The 52-case lexical suite has every reported rank metric at 1.0.

The college-algebra index has 138 documents, 17,596 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 25,153,536 bytes. The 59-case lexical suite has Success@1/5/10, Recall@5/10/50, and MRR@10 of 1.0 and nDCG@10 of 0.994477. The small nDCG gap records honest alternate-curriculum relevance rather than forcing an arbitrary single-book judgment.

The introductory-statistics index has 179 documents, 6,011 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 11,792,384 bytes. The 51-case lexical suite has every reported rank metric at 1.0.

The Microbiology index has 159 documents, 4,115 chunks and FTS rows, valid foreign keys, and a successful SQLite quick check. Its database is 11,165,696 bytes. The 57-case lexical suite has every reported rank metric at 1.0.

The gate primarily verifies named curriculum topics and parser/index stability; it is not yet a difficult paraphrase benchmark. Semantic indexing should be added only after the existing overnight embedding queue completes and a judged conceptual suite demonstrates enough hybrid-retrieval benefit to justify its GPU time and storage.
