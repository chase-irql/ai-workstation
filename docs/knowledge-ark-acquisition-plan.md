# Knowledge Ark acquisition and indexing plan

This is the storage-aware expansion queue for the offline Knowledge Ark. It records priorities before acquisition so the collection grows by measured value rather than by opportunistic downloads.

## Safety envelope

- D: had 813.35 GiB free at the start of the 2026-08-20 overnight run.
- Keep at least 200 GiB free for model files, temporary extraction, replacement indexes, database compaction, active projects, and recovery.
- Stop a batch before acquisition if its registered worst-case extracted and indexed sizes would cross that reserve.
- Any individual download larger than 20 GB requires a fresh size and scope review before it starts.
- Raw corpora, processed records, BM25 databases, semantic indexes, and evaluation output stay outside Git.

## Retrieval lifecycle

Every corpus moves through these observable states:

1. `planned`: official source, release, license, checksum, scope, paths, and storage bounds are registered.
2. `downloaded`: resumable transfer completed atomically.
3. `validated`: checksum, archive paths, member sizes, and format checks passed.
4. `parsed`: corpus-specific structure was converted to common document and chunk records with stable identifiers and citations.
5. `indexed`: a replacement SQLite FTS5 database passed integrity, foreign-key, row-count, FTS-count, and smoke-query checks before publication.
6. `evaluated`: a versioned stable-ID suite reports lexical metrics and latency.
7. `semantic`: embeddings are published only after source binding and checksum verification, and only when a paraphrase suite demonstrates useful retrieval value.
8. `served`: the corpus is added to the unified MCP configuration after its published indexes pass end-to-end tests.

## Ranked acquisition queue

### Wave 1: operational Stack Exchange sites

These reuse the bounded-memory Stack Exchange importer and therefore have the lowest implementation risk.

| Rank | Dataset | Compressed bytes | Conservative extraction + index budget | Primary value |
|---:|---|---:|---:|---|
| 1 | Network Engineering | 52,567,199 | 1.5 GB | Routing, switching, VLANs, firewalls, and protocol operations |
| 2 | Database Administrators | 334,305,094 | 8 GB | Database recovery, performance, indexing, replication, and administration |
| 3 | Electrical Engineering | 711,176,809 | 17 GB | Circuits, components, power, embedded systems, and diagnostics |
| 4 | Unix & Linux | 759,322,794 | 20 GB | Linux/Unix administration, shell, storage, boot, permissions, and recovery |
| 5 | Server Fault | 907,565,303 | 25 GB | Production servers, networking, virtualization, storage, and operations |

The first wave totals 2,764,937,199 compressed bytes. Site dumps retain every question, every accepted answer, and every other positively scored answer. Per-post license, contributor, score, tags, dates, parent relationships, and direct URLs remain attached to each record.

### Wave 2: broad and specialist technical Q&A

1. Super User (1,400,358,958 compressed bytes).
2. Ask Ubuntu (1,147,225,611 bytes).
3. Software Engineering (377,945,136 bytes).
4. Computer Science (139,405,386 bytes).
5. Raspberry Pi (108,037,406 bytes).
6. Signal Processing (93,328,686 bytes).
7. Arduino (84,936,332 bytes).

Wave 2 begins only after measured Wave 1 expansion and index sizes replace the conservative estimates. Full Stack Overflow remains gated because its acquisition and processing footprint is qualitatively larger.

### 2026-08-20 execution status

Wave 1 and the listed Wave 2 sites are downloaded, checksum-validated, extracted, parsed, BM25-indexed, and lexically evaluated. Across all 14 published Stack Exchange sites, the local installation now contains 4,511,100 retained post documents and 5,007,715 chunks. Their coordinated source archives total 6,405,663,549 bytes and their validated SQLite databases total 18,045,620,224 bytes.

Network Engineering and Database Administrators have verified 256-dimensional semantic generations. Electrical Engineering, Unix & Linux, and Server Fault are processed by a storage-guarded sequential semantic queue. The remaining Wave 2 sites stay BM25-first until paraphrase suites demonstrate that the vector storage and build time provide measurable value.

Wave 3 has begun with the official split-HTML Bash 5.3, Coreutils 9.11, Gawk 5.4, Grep 3.12, and Make 4.4.1 manuals. Together they add 1,091 canonical documents and 2,883 chunks for less than 1.8 MB of source archives and about 9.4 MB of BM25 databases—an example of the high knowledge-per-byte material this plan prioritizes.

The next GNU batch adds Sed, Tar, Findutils, and Diffutils: another 738 documents and 1,490 chunks for 648,031 compressed source bytes. Every corpus has a verified database and a perfect six-topic lexical regression gate. Small official manuals are intentionally embedded only after larger conceptual corpora, because BM25 already answers their exact command and option lookups well.

The third batch adds glibc 2.44, Gzip 1.14, Wget 1.25.0, and GRUB 2.14: 1,437 documents and 3,623 chunks from 1,730,159 compressed source bytes. These fill four practical offline gaps—C/POSIX APIs, compression validation, resilient acquisition/mirroring, and bootloader recovery—while retaining canonical per-node citations and exact upstream license notices.

The first Wave 4/manual pilot is also complete. FAA-H-8083-30B (2023) exercises the page-aware PDF path on a real 92,539,602-byte engineering handbook: 676 of 677 pages have searchable text, one cover is image-only, and 1,837 page-bounded chunks feed a verified 9,388,032-byte BM25 database. The importer retains outline/page citations and rotated labels, demotes front-matter matches, and fails atomically when a scan requires OCR. This makes it safe to expand into selected FAA, DOE, NASA, NIST, USACE, and equipment-specific manuals without pretending an image-only archive is searchable.

### Wave 3: official programming and systems documentation

Acquire pinned official releases with publisher checksums where available:

- Bash and GNU manuals: coreutils, grep, sed, gawk, make, binutils, GDB, and glibc.
- Linux kernel documentation, systemd, OpenSSH, OpenSSL, CMake, Ninja, Docker, Podman, and Kubernetes.
- PostgreSQL, Nginx, Apache HTTP Server, GCC, LLVM/Clang, Rust, Go, Java, Node.js, TypeScript, and .NET documentation.

Documentation records preserve project, release, manual/page, heading hierarchy, code blocks, anchors, license, and canonical source URL. BM25 is the first publication gate; semantic indexing follows only for prose-heavy corpora with a judged paraphrase suite.

### Wave 4: textbooks, repair, and practical knowledge

- OpenStax complete collection, then curated Open Textbook Library and LibreTexts learning sequences.
- English Wikibooks.
- iFixit and personally owned equipment manuals.
- Hesperian guides, appropriate-technology collections, and selected WHO, FAO, USDA, FEMA, DOE, NASA, USACE, NIST, and FAA handbooks.
- MIT OpenCourseWare courses with notes, assignments, labs, exams, and solutions; omit most video while storage is constrained.

Keep EPUB/HTML/XML for retrieval and PDFs when diagrams, equations, tables, schematics, or page references matter. OCR-derived text must retain its page and source-image relationship.

### Wave 5: structured and large collections

- Wiktionary, NIST DLMF, CODATA, GeoNames, FoodData Central, and selected compact scientific databases.
- PubMed baseline, arXiv metadata/abstracts, regional OpenStreetMap and elevation data, and curated offline software repositories.
- PMC Open Access, larger arXiv PDF subsets, Wikidata, and distribution package mirrors after the planned HDD is available.

Structured databases and geographic data receive purpose-built query adapters; they are not flattened blindly into ordinary text chunks.

## Evaluation and embedding policy

- Create corpus-specific lexical suites from stable document IDs before embedding.
- Include exact identifiers, common terminology, troubleshooting queries, and ambiguous cases.
- Create a separate paraphrase suite with pooled graded judgments for semantic evaluation.
- Compare BM25, semantic, hybrid, and routed/reranked paths. Do not describe evidence packing as an improvement when top-rank metrics fall.
- Start large corpora with Qwen3-Embedding 0.6B at 256 dimensions. Rebuild at 1,024 dimensions only when a judged suite shows enough improvement to justify four times the vector storage.
- Preserve `content_id` reuse across corpus updates so unchanged chunks do not need to be embedded again.

## Update policy

New releases are acquired beside the current generation. The existing corpus remains served until the replacement passes checksum, parse, index, citation, evaluation, and source-binding checks. Stable upstream IDs remain stable across releases; changed or removed evaluation judgments require a new suite version rather than silent edits.
