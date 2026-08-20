# Corpus catalog

This catalog is the human-readable inventory of every corpus currently published by the development installation. The repository contains acquisition metadata, importers, and evaluation suites; it intentionally does not redistribute source archives, processed records, indexes, or vectors.

`config/datasets.json` is the machine-readable registry for documentation and structured datasets. Wikipedia retains its own dump manifest because its multistream acquisition and update lifecycle are different. Generated acquisition manifests, corpus manifests, SQLite metadata, vector manifests, and evaluation reports are the run-specific evidence behind this summary.

## Published corpora

| Corpus ID | Pinned source | License / terms | Local scale | Retrieval |
|---|---|---|---:|---|
| `wikipedia` | English Wikipedia `enwiki-20260801` | CC BY-SA 4.0 and GFDL; Wikimedia attribution requirements apply | 7,215,325 searchable articles; 35.8M chunks | BM25 + article-level semantic/hybrid |
| `python-3.14-docs` | Python 3.14.7 HTML documentation | PSF License 2.0; examples additionally 0BSD | 565 documents; 8,840 chunks | BM25 + chunk-level semantic/hybrid |
| `git-docs` | Git 2.55.0 source documentation | GPL-2.0-only with Git documentation terms | 985 documents; 4,953 chunks | BM25 + chunk-level semantic/hybrid |
| `linux-man-pages` | Linux man-pages 6.18 | Per-page licenses retained in the source | 1,245 documents; 13,155 chunks | BM25 + chunk-level semantic/hybrid |
| `rfc-editor-text` | RFC Editor snapshot 2026-08-19 | IETF Trust Legal Provisions | 9,822 RFCs; 348,831 chunks | BM25 + chunk-level semantic/hybrid |
| `iana-protocol-registries` | IANA assignments snapshot 2026-08-19 | CC0 1.0 Universal | 4,256 registries; 110,423 table records; 114,590 chunks | Structured BM25 |
| `sqlite-docs` | SQLite 3.53.4 static HTML documentation | Public domain | 765 documents; 4,384 chunks | BM25 + chunk-level semantic/hybrid |
| `cmake-4.4-docs` | CMake 4.4.2 `Help/*.rst` source documentation | BSD 3-Clause | 2,144 documents; 4,226 chunks | BM25 |
| `openssl-4.0-docs` | OpenSSL 4.0.1 POD manuals | Apache-2.0 | 960 manuals; 8,287 chunks | BM25 |
| `openssh-10.5p1-docs` | OpenSSH Portable 10.5p1 manuals | BSD-style OpenSSH licenses | 19 documents; 195 chunks | BM25 |
| `ninja-1.13-docs` | Ninja 1.13.2 manual at commit `3441b633…` | Apache-2.0 | 1 manual; 58 chunks | BM25 |
| `postgresql-18-docs` | PostgreSQL 18.6 generated HTML documentation | PostgreSQL License | 1,148 documents; 6,931 chunks | BM25 |
| `systemd-261-docs` | systemd 261.2 DocBook manuals and Markdown guides | LGPL-2.1-or-later; per-file notices retained | 542 documents; 9,614 chunks | BM25 |
| `faa-amt-general-2023` | FAA-H-8083-30B Aviation Maintenance Technician Handbook — General (2023) | U.S. Government work; handbook notices govern any third-party material | 677 pages; 1,837 chunks | Page-aware BM25 |
| `bash-5.3-manual` | GNU Bash 5.3 split-HTML manual, generated 2025-07-04 | GFDL 1.3 or later, with no invariant or cover texts | 132 documents; 386 chunks | BM25 |
| `coreutils-9.11-manual` | GNU Coreutils 9.11 split-HTML manual, generated 2026-04-20 | GFDL; exact notices retained | 253 documents; 639 chunks | BM25 |
| `gawk-5.4-manual` | GNU Awk 5.4 split-HTML manual, generated 2026-02-22 | GFDL 1.3 or later with stated invariant and cover texts | 502 documents; 1,332 chunks | BM25 |
| `grep-3.12-manual` | GNU Grep 3.12 split-HTML manual, generated 2025-04-11 | GFDL; exact notices retained | 31 documents; 82 chunks | BM25 |
| `make-4.4.1-manual` | GNU Make 4.4.1 split-HTML manual, generated 2023-02-26 | GFDL; exact notices retained | 173 documents; 444 chunks | BM25 |
| `sed-manual-20260422` | GNU Sed split-HTML manual, generated 2026-04-22 | GFDL; exact notices retained | 67 documents; 174 chunks | BM25 |
| `tar-manual-20260611` | GNU Tar 1.35.90 split-HTML manual, generated 2026-06-11 | GFDL; exact notices retained | 411 documents; 733 chunks | BM25 |
| `findutils-manual-20260714` | GNU Findutils 4.11.0 split-HTML manual, generated 2026-07-14 | GFDL; exact notices retained | 147 documents; 337 chunks | BM25 |
| `diffutils-3.12-manual` | GNU Diffutils 3.12 split-HTML manual, generated 2025-04-09 | GFDL 1.3 or later with no invariant or cover texts | 113 documents; 246 chunks | BM25 |
| `glibc-2.44-manual` | GNU C Library 2.44 split-HTML manual, generated 2026-07-27 | GFDL 1.3 or later with stated invariant and cover texts | 776 documents; 2,164 chunks | BM25 |
| `gzip-1.14-manual` | GNU Gzip 1.14 split-HTML manual, generated 2025-04-10 | GFDL 1.3 or later with no invariant or cover texts | 10 documents; 30 chunks | BM25 |
| `wget-1.25-manual` | GNU Wget 1.25.0 split-HTML manual, generated 2024-11-11 | GFDL; exact notices retained | 51 documents; 149 chunks | BM25 |
| `grub-2.14-manual` | GNU GRUB 2.14 split-HTML manual, generated 2026-01-14 | GFDL 1.2 or later with no invariant sections | 600 documents; 1,280 chunks | BM25 |
| `devops-stackexchange` | DevOps Stack Exchange 2026-06-30 community dump | CC BY-SA 3.0 or 4.0 per retained post | 11,877 retained posts; 13,531 chunks | BM25 + experimental 1,024-dim semantic/hybrid |
| `security-stackexchange` | Information Security Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 171,041 retained posts; 188,770 chunks | BM25 + 256-dim semantic/hybrid |
| `networkengineering-stackexchange` | Network Engineering Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 39,592 retained posts; 44,174 chunks | BM25 + 256-dim semantic/hybrid |
| `dba-stackexchange` | Database Administrators Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 220,788 retained posts; 262,323 chunks | BM25 + 256-dim semantic/hybrid |
| `electronics-stackexchange` | Electrical Engineering Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 509,806 retained posts; 545,211 chunks | BM25; semantic generation in progress |
| `unix-stackexchange` | Unix & Linux Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 528,891 retained posts; 602,485 chunks | BM25; semantic generation queued |
| `serverfault-stackexchange` | Server Fault Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 704,713 retained posts; 775,708 chunks | BM25; semantic generation queued |
| `softwareengineering-stackexchange` | Software Engineering Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 214,014 retained posts; 239,207 chunks | BM25 |
| `cs-stackexchange` | Computer Science Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 101,644 retained posts; 109,770 chunks | BM25 |
| `arduino-stackexchange` | Arduino Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 52,338 retained posts; 62,506 chunks | BM25 |
| `raspberrypi-stackexchange` | Raspberry Pi Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 75,998 retained posts; 85,362 chunks | BM25 |
| `dsp-stackexchange` | Signal Processing Stack Exchange 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 60,376 retained posts; 66,988 chunks | BM25 |
| `superuser-stackexchange` | Super User 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 1,030,135 retained posts; 1,110,380 chunks | BM25 |
| `askubuntu-stackexchange` | Ask Ubuntu 2026-06-30 community dump | CC BY-SA 2.5, 3.0, or 4.0 per retained post | 789,887 retained posts; 901,300 chunks | BM25 |

Counts describe the pinned local generations, not upstream projects in perpetuity. Evaluation suites are small, versioned regression gates rather than broad claims about corpus completeness or answer accuracy.

The 14 Stack Exchange generations total 4,511,100 retained post documents, 5,007,715 chunks, 6,405,663,549 compressed source bytes, and 18,045,620,224 bytes of validated BM25 databases. Source archives, processed records, indexes, and run results remain local and are not redistributed by this repository.

## Provenance and update records

### English Wikipedia

- Raw source: `corpora/raw/wikipedia/enwiki-20260801/`.
- Processed generation: `corpora/processed/wikipedia/enwiki-20260801/full/`.
- BM25 index: `indexes/wikipedia/enwiki-20260801-full.sqlite3`.
- Semantic generation: `indexes/wikipedia/enwiki-20260801-semantic-full/`.
- Publisher verification: Wikimedia SHA1 for both the multistream XML/BZip2 archive and multistream index.
- Update procedure: [wikipedia-corpus-updates.md](wikipedia-corpus-updates.md).

### Python documentation

- Official archive: `https://docs.python.org/3/archives/python-3.14-docs-html.zip`.
- Local archive SHA-256: `9306da398ae5a9142deb22d5c7865994fe0ada961022c8dea8ee341348e14181`.
- The publisher archive listing did not supply a digest; ZIP member CRCs and structure are validated and the local digest pins the acquired artifact.
- Processed/index paths and update frequency are recorded under `python-3.14-docs` in `config/datasets.json`.

### Git documentation

- Official archive: kernel.org Git 2.55.0 release source.
- Publisher SHA-256: `457fdb04dc8728e007d4688695e6912e6f680727920f2a40bf11eacc17505357`.
- The importer preserves AsciiDoc/man structure, relative source paths, and version-pinned kernel.org citations.

### GNU Bash reference manual

- Official archive: `https://www.gnu.org/software/bash/manual/bash.html_node.tar.gz`.
- Local archive SHA-256: `aa0bcdf6270035e061ffaca40f9f74dd879b2fe4d812cfbb12828ca7998ec0c3`.
- GNU does not publish an adjacent cryptographic digest for this generated manual archive; acquisition therefore records the local digest and validates every tar member and extracted byte count.
- The split-HTML structure preserves one canonical GNU manual URL per node. The 12-topic stable-ID lexical gate passes all ranking cutoffs.

### GNU systems manuals

- Coreutils 9.11, Gawk 5.4, Grep 3.12, and Make 4.4.1 use the same official generated split-HTML publication format and canonical per-node URLs.
- GNU does not provide adjacent cryptographic digests for these generated documentation archives. Each acquisition manifest pins a local SHA-256 and records the exact download URL, generation label, tar member inventory, extracted byte count, and validation result.
- The four archives produced 959 documents and 2,497 chunks. Each six-topic stable-ID lexical gate passes every ranking cutoff.
- Gawk includes two pairs of upstream paths distinguished only by case. The importer preserves both with deterministic collision IDs while leaving all ordinary path-derived IDs unchanged.
- Sed, Tar, Findutils, and Diffutils use the same validated publication path. Their 738 documents and 1,490 chunks cover stream editing, archives and recovery, safe file traversal, command batching, comparisons, patches, and merging.
- glibc 2.44, Gzip 1.14, Wget 1.25.0, and GRUB 2.14 add 1,437 documents and 3,623 chunks covering C/POSIX interfaces, compression integrity, resilient downloads, and boot recovery. The glibc archive is pinned directly from the official Sourceware publication rather than the insecure redirect on the legacy GNU URL.

### Linux man-pages

- Official archive: kernel.org man-pages 6.18 release.
- Publisher SHA-256: `c934fadc8b59748c68227a34f6581d2ddf8282b73cdcd52546c8cd88b74b24d1`.
- Alias pages are not duplicated; per-page license notices remain in source text and provenance.

### RFC Editor

- Acquisition: official `rsync://rsync.rfc-editor.org/rfcs-text-only` snapshot.
- Source inventory: 10,057 regular files, 555,449,714 bytes, aggregate SHA-256 `8d575f0b1785b6c5ac710f48ce7c4ee129e9d79d81f7e7686726f2a23f4d3ac2`.
- The importer preserves RFC number, publication status/date, ISSN, obsoletes, updates, section hierarchy, and stable RFC Editor citations.

### IANA protocol registries

- Acquisition: official `rsync://rsync.iana.org/assignments` snapshot.
- Source inventory: 8,269 regular files, 70,672,402 bytes, aggregate SHA-256 `7c8e859136528cfe12aab4840f837ede1d8054541c50a7126cdcb8c05257b462`.
- The table-aware importer preserves nested registries, field names, row values, references, timestamps, and stable IANA URL fragments. It remains BM25-first because ports, protocol numbers, media types, and parameter codes are primarily exact lookups.

### SQLite documentation

- Official archive: `https://www.sqlite.org/2026/sqlite-doc-3530400.zip`.
- Publisher SHA3-256: `7ccf86a52e7dd1fb9b31e63edcebe3b553f18f89cd26eef59c7f191a5111836e`.
- Local archive SHA-256: `a1d0f5de57485d062796ed7e67daff0758b50d00001a0f233a2c15aaf40bbdc8`.
- The HTML importer preserves headings, code, lists, API identifiers, SQL terms, and stable `sqlite.org` citations while excluding navigation and search furniture.

### FAA Aviation Maintenance Technician Handbook — General

- Official PDF: `https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/amtg_handbook.pdf`.
- The 92,539,602-byte artifact is pinned by local SHA-256 `0a39c01bbc454e77a49813cf27e2ef291756fa7111d9308bc290cd0eb71616fd`; the FAA publication page does not provide an adjacent digest.
- The PDF has 677 pages. The text-layer gate found 676 searchable pages and one image-only cover, producing 1,837 chunks without crossing page boundaries.
- PDF title/author metadata, outline hierarchy, page labels, source digest, release, license, and canonical URL are retained. Rotated table and diagram text is included even where spacing is degraded.
- The 14-topic lexical suite passes every cutoff. Because the pilot contains one document, this is a coverage gate rather than a claim about inter-document ranking; sampled citations correctly resolve topics including Ohm's law (page 12-17), eddy-current inspection (page 10-20), corrosion (page 8-10), and torque-wrench calibration (page 11-6).
- Table-of-contents/front-matter chunks remain searchable but rank behind matching body evidence. OCR remains an explicit future preprocessing step for low-text scans.

### CMake 4.4 documentation

- Official source archive: `https://github.com/Kitware/CMake/releases/download/v4.4.2/cmake-4.4.2.tar.gz`.
- Publisher SHA-256: `1db9e61e60b6e0874c86386340b910382f3c5e75b9fbfb44d122063129a2789d` from Kitware's signed release checksum asset.
- The scope is the complete `Help/*.rst` tree: 2,408 candidate files, 2,144 nonempty structured documents, and 4,226 chunks. Commands, variables, properties, policies, generators, modules, manuals, and release notes retain version-pinned source citations.
- The 12-topic lexical gate achieved Success@1/5/10, MRR@10, and Recall@5/10/50 of `1.0`; nDCG@10 is `0.996621` due to equivalent relevant install/interface documentation.

### OpenSSL 4.0 documentation

- Official source archive: `https://github.com/openssl/openssl/releases/download/openssl-4.0.1/openssl-4.0.1.tar.gz`.
- Publisher SHA-256: `2db3f3a0d6ea4b59e1f094ace2c8cd536dffb87cdc39084c5afa1e6f7f37dd09` from the adjacent OpenSSL checksum asset.
- The POD importer handles both `.pod` and release-generated `.pod.in` sources. It preserves NAME-derived titles, section hierarchy, command options, inline markup, links, and verbatim examples across 960 manuals and 8,287 chunks.
- The 13-topic lexical gate covers certificate verification, TLS diagnostics, PKCS#12, key/certificate generation, randomness, BIO, OCSP stapling, FIPS installation, peer verification, digest fetching, and hostname checking; every metric cutoff passed at `1.0`.

### OpenSSH Portable 10.5p1 manuals

- Official archive: `https://cdn.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-10.5p1.tar.gz`.
- Local SHA-256: `d44d28a839ea9daf969cc69150fde59910b2b39361dad81a3bd6cbd19218db11`. The upstream detached signature URL is recorded in the registry, but this run does not claim signature verification because no configured OpenPGP verifier was available.
- The source archive passed full member/path/size validation. Sixteen section 1/5/8 manuals plus three scoped Markdown documents produced 195 chunks with pinned tag citations.
- OpenSSH's manuals use OpenBSD `mdoc`; the shared roff parser now preserves `It`, `Cm`, `Fl`, `Ar`, `Pa`, `Xr`, and related semantic macros. This was verified by a failed-before-fix `PubkeyAuthentication` smoke query and passing parser regression.
- The 12-topic lexical gate covers server/client configuration, key revocation and certificates, SFTP/SCP, host-key scanning, authorized-key restrictions, agents, forwarding, and Diffie-Hellman moduli; all cutoffs pass at `1.0`.

### Ninja 1.13.2 manual

- Source is pinned by immutable commit `3441b633c2fe2c494e958780ba0f4227b1327634`, the object behind v1.13.2. Local source-archive SHA-256 is `bccc6197cd8c3ac2a439e26d6bf41506fe49c430cf3d593269a15379f24266ee`.
- The one authoritative AsciiDoc manual produces 58 structured chunks covering build syntax, implicit/order-only dependencies, dyndep, depfiles, pools, response files, rule variables, scoping, tools, and default targets.
- Its 11-topic lexical coverage gate passes every cutoff at `1.0`. This is a single-document coverage check, not an inter-document ranking claim.

### PostgreSQL 18.6 documentation

- Official archive: `https://ftp.postgresql.org/pub/source/v18.6/postgresql-18.6-docs.tar.gz`.
- The 3,906,887-byte artifact is pinned by local SHA-256 `0419dec0d3b7ca55a80c0519a1dd88a8d172019ef9841288889f0281ea1f97ed`. PostgreSQL does not publish an adjacent digest for this docs-only archive, so the acquisition record explicitly distinguishes the local digest from a publisher checksum.
- All 1,449 archive members and 19,416,147 extracted bytes passed path, size, and format validation. The complete generated HTML set produced 1,148 documents, 6,931 chunks, and a verified 22,126,592-byte BM25 database.
- The 18-topic stable-ID gate exercises recovery, routine vacuuming, MVCC, concurrent indexes, query analysis, statistics, physical and logical replication, row security, JSONB indexes, deadlocks, partition pruning, backup, SCRAM authentication, full-text search, and generated/identity columns. Success@1/5/10, MRR@10, and Recall@10/50 are `1.0`; Recall@5 is `0.972222` and nDCG@10 is `0.985629` because some queries have multiple graded relevant references.

### systemd 261.2 documentation

- Source is pinned by immutable commit `4925d9f07fc697efccd98a93046ff535b8832445`, the object referenced by systemd's signed v261.2 annotated tag. The 18,468,555-byte GitHub commit archive has local SHA-256 `018b0aa52a3a5d792233a3a599dd8d7dfb6302442bde88da37b0ccf847ecb54d`; GitHub does not provide an adjacent publisher digest for that generated archive.
- The complete archive passed member, path, and size validation: 7,193 regular files and 100,857,467 extracted bytes. The retrieval scope is all 455 published `man/*.xml` refentries plus 90 `docs/*.md` candidates; empty guides are skipped and shared DocBook fragments are incorporated through their XIncludes rather than indexed as misleading standalone pages.
- The shared documentation adapter now supports DocBook XML. It disables network DTD resolution, converts build-time entities deterministically, resolves only same-directory include fragments by stable XML ID, preserves section hierarchy, option definitions, lists, tables, code examples, admonitions, and man-page cross-references, and extracts Markdown YAML front matter without polluting titles or searchable text.
- The final generation contains 542 documents and 9,614 chunks in a verified 17,846,272-byte BM25 database. A 23-topic gate covering service restart limits, journal storage, timers, network configuration, DNSSEC, automounts, credentials, resource controls, socket activation, boot analysis, coredumps, containers, tmpfiles, watchdogs, portable services, sandboxing, online readiness, cryptenrollment, and boot control passes every cutoff at `1.0`.

### DevOps Stack Exchange

- Archive: June 30, 2026 coordinated community release hosted by Internet Archive.
- Publisher/coordinated SHA-256: `a08a86c7c386c0f0798817e64ecde03368908c7ed1cf90d2259f8f209421114b`.
- The importer retains every question, every accepted answer regardless of score, and other answers only when their score is positive. It excluded 1,503 answers under that policy.
- Each retained post is a separate document with a direct question or answer URL. Parent-question relationships, accepted status, title, tags, score, dates, contributor attribution, exact `ContentLicense`, HTML headings, lists, and code blocks are preserved.
- The 19-case exact-term suite passes every Success, MRR, and Recall cutoff. The 1,024-dimensional paraphrase gate reaches Success@10 `0.571429` and Recall@50 `0.642857`; semantic retrieval is published for experimentation, not presented as a solved quality problem.
- Acquisition and update procedure: [stack-exchange-ingestion.md](stack-exchange-ingestion.md).

### Information Security Stack Exchange

- Archive: June 30, 2026 coordinated community release hosted by Internet Archive; 271,298,857 bytes compressed and 1,313,984,676 bytes extracted.
- Publisher/coordinated SHA-256: `401a0d754eb2a981922ddb0494648b4be57ac2cc5bad545b1fe609118df0e6df`.
- The shared Stack Exchange importer retained 70,265 questions, 32,426 accepted answers, and 68,350 other positively scored answers. It excluded 19,964 answers under the documented quality policy.
- The published common-record generation contains 171,041 post documents and 188,770 chunks. Each question or answer retains its stable post ID, direct URL, parent relationship, score, tags, contributor attribution, dates, and exact `ContentLicense`.
- The initial 18-topic lexical gate and final automatically routed exact-query gate both achieved Success@1/5/10, MRR@10, Recall@5/10/50, and nDCG@10 of `1.0`. Automatic routing preserves strict BM25 ordering for terse technical phrases.
- A verified 256-dimensional generation binds all 188,770 vectors to the BM25 source build and occupies 287,344,685 bytes for FAISS plus metadata. On 14 pooled paraphrase judgments, hybrid retrieval achieved Success@10 `0.928571` and Recall@50 `0.704762`, while strict-AND BM25 found none. Reranking preserved Success@10 but lowered Success@5 from `0.857143` to `0.785714`; exact terms therefore remain BM25-first.
- Acquisition and update procedure: [stack-exchange-ingestion.md](stack-exchange-ingestion.md).

## Lifecycle and publication rules

Every new or updated corpus must pass the same observable stages:

1. Register its official source, pinned version/snapshot, license, scope, size bounds, paths, and update frequency.
2. Acquire resumably and publish atomically only after size, format, and available publisher-checksum validation.
3. Parse with a corpus-specific adapter into the shared document/chunk schema while retaining provenance and structure.
4. Build a replacement SQLite database beside the live index, validate it, then atomically publish it.
5. Run a stable-ID lexical evaluation suite and inspect citations.
6. Add semantic retrieval only when conceptual discovery is useful; publish vectors independently after source-identity and row-count verification.
7. Compare BM25, semantic, hybrid, and routed/reranked behavior before exposing the generation through MCP.

Generated data remains ignored by Git. Only code, registry entries, evaluation suites, and documentation are intended for repository distribution. See [data-distribution-policy.md](data-distribution-policy.md).
