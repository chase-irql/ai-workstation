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
| `nodejs-24-docs` | Node.js 24.19.0 LTS Krypton API and guides | MIT and included third-party licenses | 126 documents; 5,732 chunks | BM25 |
| `apache-httpd-2.4-docs` | Apache HTTP Server 2.4.68 English manual | Apache-2.0 | 232 documents; 3,055 chunks | BM25 |
| `docker-docs-20260820` | Official Docker docs commit `510f85c…`, 2026-08-20 | Apache-2.0 | 1,174 documents; 11,190 chunks | BM25 |
| `kubernetes-docs-20260820` | Official Kubernetes website commit `5184b9b…`, 2026-08-20 | CC-BY-4.0 | 1,605 documents; 14,164 chunks | BM25 |
| `rust-1.97-docs` | Rust 1.97.1 stable documentation distribution | MIT OR Apache-2.0; component notices retained | 7,570 documents; 57,178 chunks | BM25 |
| `typescript-docs-20260820` | Official TypeScript website commit `90e92beb…`, 2026-08-20 | CC-BY-4.0 | 77 documents; 935 chunks | BM25 |
| `gdb-17.2-manual` | GNU GDB 17.2 last-release manual | GFDL 1.3 or later with stated invariant and cover texts | 863 documents; 2,225 chunks | BM25 |
| `gcc-16.2-manual` | GNU Compiler Collection 16.2 user manual | GFDL 1.3 or later with stated invariant and cover texts | 523 documents; 1,695 chunks | BM25 |
| `linux-kernel-7.2-docs` | Linux 7.2 official source documentation | GPL-2.0-only and per-file SPDX licenses retained | 4,154 documents; 29,142 chunks | BM25 |
| `llvm-project-22.1.8-docs` | LLVM Project 22.1.8 coordinated source release | Apache-2.0 with LLVM Exceptions; per-file notices retained | 2,352 documents; 18,655 chunks | BM25 |
| `go-1.26.7-docs` | Go 1.26.7 stable source release | BSD 3-Clause; per-file notices retained | 1,320 documents; 18,647 chunks | BM25 |
| `podman-6.1-docs` | Podman 6.1.0 signed release tag | Apache-2.0 | 223 manuals/guides; 2,484 chunks | BM25 |
| `binutils-2.47-docs` | GNU Binutils 2.47 official HTML manuals | GFDL 1.3; exact manual notices retained | 8 manuals; 1,807 chunks | BM25 |
| `dotnet-docs-20260820` | Official `dotnet/docs` commit `e2fe6aca…`, 2026-08-19 | CC-BY-4.0; repository/per-file notices retained | 13,225 pages; 77,212 chunks | BM25 |
| `nginx-docs-20260820` | Official `nginx/nginx.org` commit `df444293…`, 2026-08-20 | NGINX 2-clause BSD-like license | 149 documents; 1,669 chunks | BM25 |
| `openstax-calculus` | OpenStax Calculus Volumes 1–3 commit `8dbc2ce…`, 2026-07-15 | CC BY-NC-SA 4.0; per-book attribution retained | 133 unique modules / 163 book occurrences; 11,807 chunks | BM25 |
| `openstax-university-physics` | OpenStax University Physics Volumes 1–3 commit `d0ed34a…`, 2026-06-11 | CC BY-NC-SA 4.0; per-book attribution retained | 322 unique modules / 338 book occurrences; 8,870 chunks | BM25 |
| `openstax-chemistry` | OpenStax Chemistry 2e + Atoms First 2e commit `3be4b60…`, 2026-07-08 | CC BY-NC-SA 4.0; per-book attribution retained | 176 unique modules / 298 book occurrences; 4,499 chunks | BM25 |
| `openstax-biology` | OpenStax Biology 2e + AP Courses + Concepts of Biology commit `63f8b6f…`, 2026-07-22 | CC BY-NC-SA 4.0; per-book attribution retained | 574 unique modules / 575 book occurrences; 10,795 chunks | BM25 |
| `openstax-anatomy-physiology` | OpenStax Anatomy and Physiology 2e commit `716383a…`, 2026-06-12 | CC BY-NC-SA 4.0; per-book attribution retained | 198 modules; 4,590 chunks | BM25 |
| `openstax-foundational-algebra` | OpenStax Prealgebra, Elementary Algebra, and Intermediate Algebra 2e commit `38cae454…`, 2026-06-29 | CC BY-NC-SA 4.0; per-book attribution retained | 240 modules; 33,138 chunks | BM25 |
| `openstax-college-algebra` | OpenStax Algebra and Trigonometry, College Algebra, College Algebra Corequisite Support, and Precalculus 2e commit `789b5409…`, 2026-06-12 | CC BY-NC-SA 4.0; per-book attribution retained | 138 unique modules / 319 book occurrences; 17,596 chunks | BM25 |
| `openstax-introductory-statistics` | OpenStax Introductory Statistics and Introductory Business Statistics 2e commit `1f6a3582…`, 2026-07-07 | CC BY-NC-SA 4.0; per-book attribution retained | 179 modules; 6,011 chunks | BM25 |
| `openstax-microbiology` | OpenStax Microbiology commit `63385025…`, 2026-07-08 | CC BY-NC-SA 4.0; attribution retained; educational, not current clinical guidance | 159 modules; 4,115 chunks | BM25 |
| `cpp-16.2-manual` | GNU C Preprocessor 16.2 manual | GFDL 1.3 or later with stated cover texts | 76 documents; 183 chunks | BM25 |
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

### Linux kernel documentation

- Official archive: Linux 7.2 source from kernel.org, released 2026-08-16.
- Publisher SHA-256: `f9fef3d14c0df53819026f4be74459835c2a0b0dcbf5b5bbd9ea19f0829402b3`, verified against kernel.org's signed v7.x manifest.
- The full 160,068,116-byte source archive is retained for provenance, licenses, examples, and future code-aware ingestion. Text retrieval is restricted to the English `Documentation` tree and excludes translations, build output, source code, and binary assets.
- Safe extraction validated 94,757 regular files / 1,615,609,096 bytes, skipped 99 archive links, and reversibly encoded 19,753 Windows-incompatible member names.
- The common-record generation contains 4,154 documents and 29,142 chunks. The 80,310,272-byte FTS5 database passes checksum, manifest, row-count, foreign-key, integrity, smoke-query, and citation verification.
- Its 44-topic stable-ID gate covers administration, troubleshooting, builds, synchronization, scheduling, memory, filesystems, networking, BPF, tracing, security, drivers, firmware, power management, isolation, ABI stability, and development; every lexical metric cutoff is `1.0`.

### LLVM Project documentation

- Official archive: LLVM Project 22.1.8 coordinated source release from GitHub.
- Publisher SHA-256: `922f1817a0df7b1489272d18134ee0087a8b068828f87ac63b9861b1a9965888`, verified against GitHub's release-asset digest; the matching Sigstore attestation bundle URL is retained.
- The full 167,061,596-byte source archive is retained. Retrieval scopes current documentation source trees for LLVM, Clang, clang-tools-extra, LLD, LLDB, libc++, Flang, MLIR, Polly, OpenMP, and compiler-rt while excluding historical release notes, source code, tests, and binary assets.
- Safe extraction validated 169,010 regular files / 2,023,722,863 bytes, skipped 19 archive links, and reversibly encoded 152,079 Windows-incompatible members.
- The common-record generation contains 2,352 documents and 18,655 chunks. Its 51,531,776-byte database passes source-manifest, row-count, foreign-key, FTS, integrity, smoke-query, and citation verification.
- Its 44-topic stable-ID gate covers LLVM IR/tools, optimization, JIT, profiling, sanitizers, Clang tooling and analysis, linking, debugging, libc++, MLIR, Flang, OpenMP, compiler-rt, Polly, and testing; every lexical metric cutoff is `1.0`.

### Go documentation and standard library

- Official archive: Go 1.26.7 stable source release from go.dev.
- Publisher SHA-256: `0ed24eac755105085b89fe9cabc2742b91a0ad7b94b59d3ad364918ebc8956ad`, verified against go.dev's download API together with the exact 34,150,794-byte size.
- Safe extraction validated 15,013 regular files / 145,137,149 bytes, contained no archive links, and reversibly encoded 848 Windows-incompatible members.
- A deterministic Go lexer/parser extracts package prose, exported generic and non-generic functions, methods, types and public type bodies, grouped constants and variables, and declaration signatures. It strips implementation bodies and does not execute downloaded toolchain programs.
- Internal packages, vendored dependencies, tests, testdata, and the initial-development history are excluded. Of 2,059 scoped source files, 1,320 contained public documentation and produced 18,647 chunks; 739 implementation-only files were skipped.
- The 29,020,160-byte FTS5 database passes source-manifest, row-count, foreign-key, FTS, integrity, smoke-query, and citation verification. Its 45-topic stable-ID gate covers language rules, the toolchain, generics, concurrency, networking, HTTP, cryptography, encodings, databases, runtime, testing, filesystems, templates, compression, and archives with every metric cutoff at `1.0`.

### Podman documentation

- Official archive: Podman 6.1.0 source from the signed `v6.1.0` annotated tag, resolved to commit `cade97a52ebdf9dbf9e81de8009015776837a074`.
- GitHub does not publish a digest for tag archives. The acquisition therefore pins local SHA-256 `e086183db2f852476a7fa2580d0276cef32086b4cf17ae7020948f06eb613e0d`, records the signed tag object, and does not claim publisher-checksum verification.
- Safe extraction validated the 20,956,524-byte archive as 10,195 regular files / 93,605,870 bytes, skipped 8 archive links, and reversibly encoded 1,170 Windows-incompatible member names.
- Retrieval includes canonical command manuals, configuration references, tutorials, Quadlet, Kubernetes interoperability, remote operation, and administration. Reusable option/link fragments are excluded because their material is already expanded into the canonical manual pages.
- Pandoc manual title blocks such as `% podman-run 1` are recognized, preventing generic `NAME` headings from degrading titles and citations. The generation contains 223 documents and 2,484 chunks in a 3,604,480-byte verified BM25 database.
- Its 40-topic stable-ID lexical gate covers lifecycle, images, registries, networks, volumes, pods, systemd/Quadlet, Kubernetes, machines, rootless operation, secrets, checkpoints, remote APIs, Compose, manifests, and farm builds; every metric cutoff is `1.0`.

### GNU Binutils documentation

- Official publication: all eight single-page HTML manuals generated from GNU Binutils 2.47 sources and published by Sourceware on 2026-07-26.
- A reusable bounded HTTP file-set acquisition downloads each manual independently with resume support, per-file and aggregate byte ceilings, atomic publication, and individual SHA-256 provenance. The 8 files total 6,914,167 bytes. Sourceware supplies no adjacent HTML digests, so the manifest explicitly reports zero publisher checksums verified.
- The corpus covers GNU `as`, `ld`, the binary utilities (`objdump`, `readelf`, `nm`, `ar`, `objcopy`, `strip`, and related tools), BFD, CTF, SFrame, `gprof`, and `gprofng`. Duplicate split-page HTML and PDFs are excluded.
- The upstream BFD manual's `Untitled Document` metadata is deterministically repaired to `BFD Library`. The 8 manuals produce 1,807 heading-aware chunks in a 6,664,192-byte verified FTS5 database.
- Its 33-topic stable-ID lexical gate covers assembly, linker scripts and shared objects, ELF inspection and transformation, object-file abstractions, type/debug formats, profiling, and stack-trace metadata; every metric cutoff is `1.0`.

### .NET documentation

- Official snapshot: `dotnet/docs` main commit `e2fe6aca79d1a7296241f144a43dbccf42d58a47` from 2026-08-19.
- GitHub supplies no digest for commit archives. The 274,457,692-byte archive is therefore pinned by local SHA-256 `6a65c4abc3f9b55a3612ee069ca2d2ef7149b59bf0c7461c0bade7ff15aced30` without a publisher-checksum claim.
- Safe extraction validated 23,578 regular files / 382,589,198 bytes, no archive links, and 9,161 reversibly encoded Windows-incompatible names. Samples, source code, media, and build metadata remain raw but are outside text retrieval.
- The DocFX-aware importer expands local shared includes into their canonical parent pages, rejects cycles and path traversal, and excludes fragments as standalone citations. Fifteen unavailable cross-repository include targets affect 7 Azure-oriented pages; those directives are removed and recorded on the affected documents and in extraction statistics.
- The common-record generation contains 13,225 canonical Markdown pages and 77,212 chunks. Its 167,247,872-byte FTS5 database passes source-manifest, row-count, foreign-key, integrity, smoke-query, and citation verification.
- Its 50-topic stable-ID gate covers C#, F#, Visual Basic, runtime memory, extensions, networking, serialization, security, concurrency, deployment, CLI/build tooling, diagnostics, native/COM interop, compatibility, architecture, and testing; every lexical metric cutoff is `1.0`.

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

### Node.js 24.19.0 LTS documentation

- The release was resolved from Node.js's official distribution index as the latest v24 LTS Krypton build at acquisition time. The 55,505,276-byte source archive matches publisher SHA-256 `f6d95e10a0431ee1067fc6aabe9f762908b4716dd35324e1ddb4b1466b76659f` from the adjacent official `SHASUMS256.txt`.
- All 32,303 source-release files and 578,863,312 extracted bytes passed archive validation. Retrieval includes the complete API, guide, and contributor Markdown set while excluding historical release changelogs that caused obsolete behavior to outrank the current API.
- The published generation contains 126 documents and 5,732 chunks in a verified 12,177,408-byte BM25 database. The Markdown parser removes Node's non-content HTML metadata comments while preserving comments inside code fences. Its 26-topic lexical gate spans workers, filesystem promises, streams, ESM/CommonJS/packages, buffers, cryptography, child processes, clusters, async context, events, HTTP/2/TLS/DNS, testing, permissions, diagnostics, V8, VM modules, Brotli, and WASI; all Success, MRR, and Recall cutoffs are `1.0`, with nDCG@10 `0.993615`.

### Apache HTTP Server 2.4.68 documentation

- Official source archive: `https://downloads.apache.org/httpd/httpd-2.4.68.tar.gz`. Its 10,065,436 bytes match publisher SHA-256 `ed9a9d4500fb48bb28eaffb3ba71d06ccf86d498fa13ab9f781da010cc488498`; the adjacent detached-signature URL is retained as additional provenance.
- All 3,119 source-release files and 43,134,994 extracted bytes passed archive validation. The source distribution's complete generated English manual uses `.html.en`; compound-suffix support was added to the common HTML path, and Apache header, breadcrumb, language-selector, quick-view, sitemap, and index navigation are filtered rather than embedded.
- The final generation contains 232 documents and 3,055 chunks in a verified 8,142,848-byte BM25 database. Its 30-topic gate covers proxying and FastCGI, TLS and OCSP, HTTP/2, authorization, password formats, rewrites, virtual hosts, logging, caching, compression, headers, MPM tuning, status, WebSockets, ACME, forwarded addresses, `.htaccess`, request timeouts, Lua hooks, graceful restarts, core dumps, directory indexes, and MIME handling; every metric cutoff is `1.0`.

### Docker documentation snapshot 2026-08-20

- Source is pinned to GitHub-verified immutable commit `510f85c26eeb055817763a14ac2338e20fc0d913` in Docker's official docs repository. The 29,837,619-byte commit archive has local SHA-256 `d66329e2e51d454f94ae1714de22594dee703d792a7133c4e593664402d8983d`; GitHub does not provide an adjacent publisher digest for generated commit archives.
- All 2,541 archive files and 53,237,754 extracted bytes passed structural validation. Retrieval includes Docker's 1,077 site Markdown sources and the vendored official Docker/Moby CLI, Compose, BuildKit, Engine, plugin, and component references.
- Pilot ranking caught an old Engine 20.10 release note outranking the current BuildKit secret-mount guide. Release-note, changelog, and prior-Desktop-version trees are therefore excluded explicitly rather than allowed to dilute current operational evidence. Of 1,293 remaining candidates, 119 navigation/front-matter-only files are empty after parsing and intentionally skipped.
- The published generation contains 1,174 documents and 11,190 chunks in a verified 26,365,952-byte BM25 database. Standalone Hugo presentation shortcodes are removed, while parameter placeholders inside code examples remain. Its 40-topic lexical gate spans Compose dependencies/profiles/includes/watch, Dockerfiles, BuildKit secrets/cache/multi-platform builds, networks, volumes, namespaces, seccomp/AppArmor/capabilities, live restore, logging, contexts, pruning, resources, content trust, Scout, daemon TLS/proxying, OverlayFS, Desktop backup, attestations, containerd storage, and plugins; every metric cutoff passes at `1.0`.

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
