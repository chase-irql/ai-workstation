# Offline AI Knowledge Ark — Corpus List

This is the shareable inventory of the local, offline knowledge system. It lists what the system can search; it does **not** include or redistribute the corpus files themselves.

Updated: 2026-08-22

## At a glance

- **108 total corpus families**: English Wikipedia plus 107 registry-managed datasets.
- **107 registry datasets indexed locally**; **21** currently also have semantic/vector retrieval.
- **0 registry datasets are registered, downloading, or being processed.**
- Retrieval uses SQLite FTS5/BM25 as the durable baseline, with per-corpus semantic/hybrid search where embeddings are available.
- Every registry entry records its official source, pinned release/snapshot, license or usage terms, local paths, and update notes.
- Source archives, processed text, indexes, vectors, books, manuals, and other large datasets stay outside the public Git repository.

## Wikipedia

| Corpus | Coverage | Local state |
|---|---|---|
| English Wikipedia (`enwiki-20260801`) | 7,215,325 searchable articles and roughly 35.8 million chunks | Indexed with BM25 plus article-level semantic/hybrid search |

## Biomedical Bibliographic Database

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| PubMed 2026 Annual Baseline (`pubmed-baseline-2026`) | Complete NLM PubMed bibliographic baseline with titles, abstracts where available, authors, journals, publication dates, identifiers, publication types, chemicals, grants, and MeSH indexing. | 2026 annual baseline published 2026-01-29 | Indexed (BM25) |

## Build System Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Apache Maven Documentation Snapshot (`maven-docs-20260820`) | Official Maven installation, lifecycle, POM, dependency, plugin, repository, extension, and troubleshooting documentation. | 2026-08-20 commit 761248b310d529cf02ba27ca01eaa95cb0f47172 | Indexed (BM25) |
| CMake 4.4 Documentation Source (`cmake-4.4-docs`) | Official CMake command, variable, property, module, policy, generator, manual, and release documentation. | 4.4.2 | Indexed (BM25) |
| Gradle Documentation Snapshot (`gradle-docs-20260820`) | Official Gradle user manual, DSL, build authoring, dependency management, testing, performance, and plugin development documentation. | 2026-08-20 commit 4eefc0920a9431513536d238c0194bcf30b47894 | Indexed (BM25) |
| Ninja 1.13.2 Documentation (`ninja-1.13-docs`) | Official Ninja build file syntax, command-line behavior, tools, dynamic dependencies, and embedding manual. | 1.13.2 | Indexed (BM25) |

## Compiler Toolchain Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| LLVM Project 22.1.8 Documentation (`llvm-project-22.1.8-docs`) | Official LLVM, Clang, clang-tools-extra, LLD, LLDB, libc++, Flang, MLIR, Polly, OpenMP, and compiler-rt documentation from the coordinated LLVM 22.1.8 release. | 22.1.8 | Indexed (BM25) |

## Container Orchestration Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Kubernetes Documentation Snapshot 2026-08-20 (`kubernetes-docs-20260820`) | Official Kubernetes concepts, tasks, tutorials, reference, administration, security, networking, storage, scheduling, and troubleshooting documentation. | 2026-08-20 commit 5184b9b24b288709ed36b4003f53dc1530eda2f3 | Indexed (BM25) |

## Container Platform Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Docker Documentation Snapshot 2026-08-20 (`docker-docs-20260820`) | Official Docker Engine, CLI, Compose, BuildKit, Buildx, networking, storage, security, administration, Desktop, Scout, registry, and troubleshooting documentation. | 2026-08-20 commit 510f85c26eeb055817763a14ac2338e20fc0d913 | Indexed (BM25) |
| Podman 6.1 Documentation (`podman-6.1-docs`) | Official Podman command, option, configuration, networking, storage, security, Kubernetes interoperability, Quadlet, machine, system service, and troubleshooting documentation. | v6.1.0 commit cade97a52ebdf9dbf9e81de8009015776837a074 | Indexed (BM25) |

## Database Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| PostgreSQL 18.6 Documentation (`postgresql-18-docs`) | Official PostgreSQL SQL language, administration, backup, replication, security, client, server, internals, and extension documentation. | 18.6 | Indexed (BM25) |
| SQLite Documentation (`sqlite-docs`) | Official SQLite language, API, architecture, file-format, and operational documentation. | 3.53.4 | Indexed + semantic search |

## Government Engineering Handbook

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| DOE Fundamentals Handbooks (`doe-fundamentals-handbooks`) | Official DOE training handbooks covering classical physics, electrical science, thermodynamics and fluid flow, instrumentation and control, mathematics, chemistry, engineering drawings, material science, mechanical science, nuclear physics, and reactor theory. | DOE-HDBK-1010-92 through DOE-HDBK-1019-93, Revision 0 archived set | Indexed (BM25) |
| FAA Aviation Maintenance Technician Handbook — General (`faa-amt-general-2023`) | Official FAA foundational handbook covering mathematics, physics, electricity, materials, tools, inspection, maintenance practices, and human factors for aviation technicians. | FAA-H-8083-30B-2023 | Indexed (BM25) |
| FAA Aviation Maintenance Technician Handbooks — Airframe and Powerplant (`faa-amt-airframe-powerplant-2023`) | Official FAA companion handbooks covering aircraft structures and systems, reciprocating and turbine engines, fuel and induction, lubrication, ignition, electrical systems, inspections, maintenance, and troubleshooting. | FAA-H-8083-31B and FAA-H-8083-32B, 2023 | Indexed (BM25) |

## Open Textbooks

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| OpenStax Anatomy and Physiology 2e (`openstax-anatomy-physiology`) | Complete OpenStax Anatomy and Physiology 2e sequence covering cellular organization, tissues, integumentary, skeletal, muscular, nervous, endocrine, cardiovascular, lymphatic, respiratory, digestive, urinary, reproductive systems, and human development. | openstax/osbooks-anatomy-physiology main commit 716383a4c6c16037b14d75a156c65145e75e895e, 2026-06-12 | Indexed (BM25) |
| OpenStax Astronomy 2e (`openstax-astronomy`) | Complete OpenStax Astronomy 2e textbook covering observational methods, orbits and gravity, radiation and spectra, the solar system, stars and stellar evolution, the Milky Way, galaxies, cosmology, and astrobiology. | openstax/osbooks-astronomy main commit dff6acf8df597ceda73985308f838ed38417a606, 2026-07-21 | Indexed (BM25) |
| OpenStax Biology 2e, Biology for AP Courses, and Concepts of Biology (`openstax-biology`) | Complete OpenStax biology sequences covering chemistry of life, cells, genetics, evolution, biological diversity, plant and animal structure and function, ecology, and AP-oriented and introductory curricular paths. | openstax/osbooks-biology-bundle main commit 63f8b6f8d129dd1582989bb755011e9a6d523471, 2026-07-22 | Indexed (BM25) |
| OpenStax Calculus Volumes 1–3 (`openstax-calculus`) | Complete OpenStax Calculus sequence covering functions, limits, derivatives, integrals, differential equations, sequences and series, parametric and polar coordinates, vectors, multivariable calculus, and vector calculus with examples and exercises. | openstax/osbooks-calculus-bundle main commit 8dbc2ce19e804924b2517b89ac72ee45be949d15, 2026-07-15 | Indexed (BM25) |
| OpenStax Chemistry 2e and Chemistry: Atoms First 2e (`openstax-chemistry`) | Complete OpenStax general chemistry sequences covering atoms, bonding, composition, reactions, stoichiometry, gases, thermochemistry, electronic structure, periodic properties, kinetics, equilibrium, acids and bases, thermodynamics, electrochemistry, nuclear chemistry, organic chemistry, and coordination chemistry. | openstax/osbooks-chemistry-bundle main commit 3be4b60ff501f29a445f0cacf003e5f5cc16244d, 2026-07-08 | Indexed (BM25) |
| OpenStax College Algebra, Algebra and Trigonometry, and Precalculus 2e (`openstax-college-algebra`) | Complete OpenStax college mathematics bundle containing Algebra and Trigonometry 2e, College Algebra 2e, College Algebra with Corequisite Support 2e, and Precalculus 2e. | openstax/osbooks-college-algebra-bundle main commit 789b54099106b071d1d32bfcee454fed72eb4768, 2026-06-12 | Indexed (BM25) |
| OpenStax Introductory Statistics 2e and Introductory Business Statistics 2e (`openstax-introductory-statistics`) | Complete OpenStax introductory statistics sequences covering descriptive statistics, probability, random variables, distributions, sampling, confidence intervals, hypothesis testing, regression, chi-square tests, ANOVA, and business applications. | openstax/osbooks-introductory-statistics-bundle main commit 1f6a35825395bb4aa2834cf1eca37512655f920c, 2026-07-07 | Indexed (BM25) |
| OpenStax Microbiology (`openstax-microbiology`) | Complete OpenStax microbiology textbook covering microscopy, cell structure, metabolism, microbial genetics, classification, microbial diversity, pathogenicity, epidemiology, innate and adaptive immunity, clinical microbiology, antimicrobial drugs, and infectious diseases by body system. | openstax/osbooks-microbiology main commit 633850257fbd3ccf6187b9428c55e80b69236382, 2026-07-08 | Indexed (BM25) |
| OpenStax Prealgebra, Elementary Algebra, and Intermediate Algebra 2e (`openstax-foundational-algebra`) | Three complete OpenStax prerequisite mathematics sequences covering arithmetic, fractions, decimals, ratios, geometry, signed numbers, equations, inequalities, graphs, polynomials, factoring, rational and radical expressions, quadratics, exponential and logarithmic functions, and conic sections. | openstax/osbooks-prealgebra-bundle main commit 38cae454e644abf9f0a623e876994553881597c9, 2026-06-29 | Indexed (BM25) |
| OpenStax Principles of Economics 3e bundle (`openstax-principles-economics`) | Complete OpenStax Principles of Economics 3e, Principles of Microeconomics 3e, Principles of Macroeconomics 3e, and AP micro/macro economics sequences covering markets, firms, labor, public finance, money and banking, growth, inflation, unemployment, trade, policy, inequality, and environmental economics. | openstax/osbooks-principles-economics-bundle main commit d5cadb403718ff88078259a300eddc20d38563d5, 2026-07-09 | Indexed (BM25) |
| OpenStax Psychology 2e (`openstax-psychology`) | Complete OpenStax Psychology 2e textbook covering research methods, biological psychology, consciousness, sensation and perception, learning, memory, cognition, development, motivation, personality, social psychology, industrial-organizational psychology, psychological disorders, and therapy. | openstax/osbooks-psychology main commit de7e40c91813dabdc2875df9d0709fc4f46080bb, 2026-07-09 | Indexed (BM25) |
| OpenStax University Physics Volumes 1–3 (`openstax-university-physics`) | Complete calculus-based OpenStax University Physics sequence covering mechanics, waves, thermodynamics, electromagnetism, optics, relativity, quantum mechanics, condensed matter, nuclear physics, and particle physics with examples and exercises. | openstax/osbooks-university-physics-bundle main commit d0ed34a5851119a42e3d972dfc0ff49e4663977c, 2026-06-11 | Indexed (BM25) |

## Operating System Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Linux Kernel 7.2 Documentation (`linux-kernel-7.2-docs`) | Official Linux kernel documentation covering administration, APIs, drivers, filesystems, networking, memory management, scheduling, security, tracing, BPF, build systems, and kernel development. | 7.2 | Indexed (BM25) |
| PowerShell Documentation Snapshot (`powershell-docs-20260820`) | Official PowerShell 7.6 language, shell, remoting, security, administration, module, provider, and cmdlet documentation. | 2026-08-20 commit 27138b21b41de3e2b43cfcac4a56861ca419d5eb | Indexed (BM25) |
| Sysinternals Documentation Snapshot (`sysinternals-docs-20260820`) | Official Sysinternals tool references, usage guidance, troubleshooting articles, and security/administration resources. | 2026-08-20 commit 8e3453544f1e417c481d5f6a368ce0e8bbf6a8e6 | Indexed (BM25) |
| systemd 261.2 Documentation (`systemd-261-docs`) | Official systemd manual pages and administrator/developer documentation for service management, boot, logging, networking, storage, containers, security, credentials, and resource control. | 261.2 | Indexed (BM25) |
| Win32 Desktop API Documentation Snapshot (`win32-docs-20260820`) | Official Win32 desktop API and platform documentation covering system services, security, networking, graphics, audio, UI, storage, diagnostics, COM, and device interfaces. | 2026-08-20 commit 376f699767763377725b2702e2904040a39f97b9 | Indexed (BM25) |
| Windows Server Documentation Snapshot (`windows-server-docs-20260820`) | Official Windows Server administration, identity, networking, storage, clustering, virtualization, security, and troubleshooting documentation. | 2026-08-20 commit 69803dcf5ce8a2837e1be420d1346cdb447cad8c | Indexed (BM25) |
| Windows Subsystem for Linux Documentation Snapshot (`wsl-docs-20260820`) | Official WSL installation, configuration, filesystems, networking, development, enterprise, GPU, systemd, and troubleshooting documentation. | 2026-08-20 commit 8842def77a852af26318b9ebec78063a94b068ed | Indexed (BM25) |

## Package Manager Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Bundler Documentation Snapshot (`bundler-docs-20260820`) | Official generated Bundler command, workflow, configuration, deployment, troubleshooting, and gem-authoring documentation. | 2026-08-20 generated-site commit cf6cdd77cc51c9104feecb947cc9af27ce0f6248 | Indexed (BM25) |
| Composer Documentation Snapshot (`composer-docs-20260820`) | Official Composer dependency management, repositories, schema, CLI, configuration, runtime, plugins, and troubleshooting documentation. | 2026-08-20 getcomposer.org commit acf8a43b6a379f3a5ef72ebf21979f4936a608fd | Indexed (BM25) |
| npm Documentation Snapshot (`npm-docs-20260820`) | Official npm CLI, package, registry, organization, security, authentication, and configuration documentation. | 2026-08-20 commit 404e183ea0c1f0b5d0b479175a291f70e216ade3 | Indexed (BM25) |
| pnpm Documentation Snapshot (`pnpm-docs-20260820`) | Official pnpm CLI, workspaces, catalogs, dependency resolution, stores, CI, and configuration documentation. | 2026-08-20 commit 4096ad35b19c7d7e0c2c64c704c57daf5bb91668 | Indexed (BM25) |
| Swift Package Manager Documentation Snapshot (`swiftpm-docs-20260820`) | Official SwiftPM package creation, manifests, dependency resolution, registries, plugins, commands, security, and API documentation. | 2026-08-20 commit 8623e3450cea11294c69b896a639a8a5c1d1e95f | Indexed (BM25) |
| Yarn Berry Documentation Snapshot (`yarn-berry-docs-20260820`) | Official modern Yarn guides, Plug'n'Play, workspaces, constraints, configuration, protocols, CLI, and package architecture documentation. | 2026-08-20 commit 57081c05a398f25c92df1dc78752f2053576cec0 | Indexed (BM25) |

## Practical Health Guides

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Hesperian English Health Guides (`hesperian-english-health-guides-20260820`) | The official English Hesperian chapter-PDF catalog: practical community health, first aid, oral health, midwifery, disability, mental health, environmental health, occupational safety, and health-worker education guides. | English PDF catalog snapshot 2026-08-20; named guide editions 2000-2026 | Indexed (BM25) |

## Programming Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Git Documentation (`git-docs`) | Official Git command references, user manual, technical notes, and release documentation. | 2.55.0 | Indexed + semantic search |
| GNU Awk 5.4 User's Guide (`gawk-5.4-manual`) | Official GNU Awk language, programming, debugging, networking, extension, and implementation guide. | 5.4-manual-2026-02-22 | Indexed (BM25) |
| GNU C Library 2.44 Manual (`glibc-2.44-manual`) | Official glibc reference for ISO C, POSIX, GNU extensions, memory, processes, files, networking, threads, locales, and system interfaces. | 2.44-manual-2026-07-27 | Indexed (BM25) |
| GNU Make 4.4.1 Manual (`make-4.4.1-manual`) | Official GNU Make reference covering makefiles, rules, recipes, variables, functions, conditionals, implicit rules, and extensions. | 4.4.1-manual-2023-02-26 | Indexed (BM25) |
| Python 3.14 Documentation (`python-3.14-docs`) | Official Python language, standard-library, tutorial, HOWTO, and C API documentation. | 3.14.7 | Indexed + semantic search |

## Programming Language Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| cppreference C and C++ Reference (`cppreference-20250209`) | Practical offline C and C++ language and standard-library reference, including examples and version annotations. | offline HTML book 2025-02-09 | Indexed + semantic search |
| Go 1.26.7 Documentation and Standard Library (`go-1.26.7-docs`) | Official Go language documentation, command guidance, standard-library package documentation, exported APIs, declaration signatures, and package examples from the Go 1.26.7 source release. | go1.26.7 | Indexed (BM25) |
| Java SE and JDK 26 Documentation (`java-se-jdk-26-docs`) | Versioned Java SE 26 language, virtual-machine, API, tool, security, core-library, monitoring, troubleshooting, packaging, and migration documentation. | Java SE and JDK 26 documentation snapshot 2026-08-20 | Indexed + semantic search |
| Kotlin Documentation Snapshot (`kotlin-docs-20260820`) | Official Kotlin language, standard library concepts, JVM/JS/Native/Wasm, coroutines, multiplatform, build-tool, testing, and interoperability guides. | 2026-08-20 commit 0f0ac32607f2aba49240c89902deacdd4d099c1f | Indexed + semantic search |
| MDN JavaScript and Web API Documentation Snapshot (`mdn-javascript-20260820`) | Current English MDN JavaScript guide/reference plus browser Web API documentation from the official content repository. | 2026-08-20 commit 69010c9e951c5f70694282f5f4980db31d4bcb08 | Indexed + semantic search |
| Node.js 24.19.0 LTS Documentation (`nodejs-24-docs`) | Official Node.js LTS API, command-line, diagnostics, permissions, modules, packages, testing, networking, streams, workers, and contributor documentation. | 24.19.0 LTS Krypton | Indexed (BM25) |
| PHP English Manual Snapshot (`php-manual-en-20260820`) | Complete official PHP English language, security, configuration, function, class, extension, migration, and platform manual. | official generated manual dated 2026-08-20 | Indexed + semantic search |
| Ruby 4.0 Documentation (`ruby-4.0-docs`) | Official generated Ruby 4.0 syntax, core class, standard-library, extension, security, concurrency, and runtime documentation. | Ruby 4.0 documentation snapshot 2026-08-20 | Indexed + semantic search |
| Rust 1.97.1 Documentation (`rust-1.97-docs`) | Official Rust language books, reference, standard library API, compiler, Cargo, rustdoc, embedded, edition, and error-code documentation. | Rust 1.97.1 stable (2026-07-16 distribution) | Indexed (BM25) |
| The Swift Programming Language Snapshot (`swift-book-20260820`) | Official Swift language guide and reference covering syntax, semantics, concurrency, memory safety, generics, protocols, macros, and interoperability. | 2026-08-20 commit fb79af5d00ddd4e64d5431f33cfe7a0b17b6e3b8 | Indexed + semantic search |
| TypeScript Documentation Snapshot 2026-08-20 (`typescript-docs-20260820`) | Official TypeScript handbook, language reference, JavaScript guidance, module reference, declaration-file guidance, tutorials, and project configuration documentation. | 2026-08-20 commit 90e92beb7b1da8c5408f2cf0fb83c55d380a2886 | Indexed (BM25) |

## Programming Language Specification

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| ECMAScript 2026 Language Specification (`ecmascript-2026-spec`) | Signed ES2026 errata snapshot of ECMA-262, the normative ECMAScript language specification. | ES2026 July 27 errata, signed tag commit d89c03f2db8a597bc915b363a6518d0cc8acdbc0 | Indexed + semantic search |

## Programming Platform Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| .NET Documentation Snapshot (`dotnet-docs-20260820`) | Official Microsoft .NET, C#, F#, Visual Basic, runtime, libraries, deployment, architecture, desktop, cloud, data, and application-development conceptual documentation. | main commit e2fe6aca79d1a7296241f144a43dbccf42d58a47, 2026-08-19 | Indexed (BM25) |

## Programming Tool Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| GNU Binutils 2.47 Documentation (`binutils-2.47-docs`) | Official GNU assembler, linker, binary utilities, BFD, CTF, SFrame, gprof, and gprofng manuals. | 2.47, published 2026-07-26 | Indexed (BM25) |
| GNU C Preprocessor 16.2 Manual (`cpp-16.2-manual`) | Official GNU preprocessor reference covering include resolution, macro expansion, conditionals, diagnostics, pragmas, binary resource inclusion, invocation, and implementation details. | 16.2.0 | Indexed (BM25) |
| GNU Compiler Collection 16.2 Manual (`gcc-16.2-manual`) | Official GCC user manual covering compiler options, C and C++ extensions, target features, diagnostics, optimization, sanitizers, instrumentation, coverage, LTO, and compatibility. | 16.2.0 | Indexed (BM25) |
| GNU GDB 17.2 Manual (`gdb-17.2-manual`) | Official GNU debugger guide covering execution control, breakpoints, stack and data inspection, core files, remote targets, tracing, Python extensions, and the machine interface. | 17.2-manual-2026-05-10 | Indexed (BM25) |

## Repair Guides

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| iFixit English Offline Archive (`ifixit-english-2025-12`) | Complete English iFixit repair-guide snapshot packaged by Kiwix, including structured procedure pages and their offline media assets. | Kiwix English all snapshot 2025-12, published 2025-12-23 | Indexed + semantic search |

## Security And API Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| OpenSSL 4.0 Documentation (`openssl-4.0-docs`) | Official OpenSSL command, library API, configuration, provider, protocol, certificate, and cryptography manuals. | 4.0.1 | Indexed (BM25) |

## Security And System Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| OpenSSH Portable 10.5p1 Manuals (`openssh-10.5p1-docs`) | Official OpenSSH client, server, key, agent, file-transfer, configuration, and operational manual pages. | 10.5p1 | Indexed (BM25) |

## Standards

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| RFC Editor Text Collection (`rfc-editor-text`) | Complete text RFC, BCP, STD, FYI, and IEN publication collection and indexes. | snapshot-2026-08-19 | Indexed + semantic search |

## Structured Standards Data

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| IANA Protocol Registries (`iana-protocol-registries`) | Structured protocol numbers, media types, ports, parameters, and related registries. | snapshot-2026-08-19 | Indexed (BM25) |

## System Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| GNU Bash 5.3 Reference Manual (`bash-5.3-manual`) | Official GNU Bash shell language and builtin-command reference in split HTML form. | 5.3-manual-2025-07-04 | Indexed (BM25) |
| GNU Coreutils 9.11 Manual (`coreutils-9.11-manual`) | Official reference for the GNU core file, text, shell, and system utilities. | 9.11-manual-2026-04-20 | Indexed (BM25) |
| GNU Diffutils 3.12 Manual (`diffutils-3.12-manual`) | Official reference for diff, diff3, sdiff, cmp, patch formats, directory comparison, and three-way merging. | 3.12-manual-2025-04-09 | Indexed (BM25) |
| GNU Findutils 4.11.0 Manual (`findutils-manual-20260714`) | Official reference for find, locate, updatedb, and xargs, including traversal, expressions, security, and optimization. | manual-2026-07-14 | Indexed (BM25) |
| GNU Grep 3.12 Manual (`grep-3.12-manual`) | Official GNU Grep reference covering regular expressions, matching, output, recursion, environment, and diagnostics. | 3.12-manual-2025-04-11 | Indexed (BM25) |
| GNU GRUB 2.14 Manual (`grub-2.14-manual`) | Official GRUB bootloader reference covering installation, configuration, booting, rescue mode, filesystems, security, commands, and utilities. | 2.14-manual-2026-01-14 | Indexed (BM25) |
| GNU Gzip 1.14 Manual (`gzip-1.14-manual`) | Official GNU Gzip reference for compression, decompression, file handling, formats, advanced use, environment, and diagnostics. | 1.14-manual-2025-04-10 | Indexed (BM25) |
| GNU Sed Manual (`sed-manual-20260422`) | Official GNU Sed stream-editor reference covering scripts, commands, regular expressions, execution cycles, extensions, and troubleshooting. | manual-2026-04-22 | Indexed (BM25) |
| GNU Tar Manual (`tar-manual-20260611`) | Official GNU Tar reference for archive creation, extraction, formats, verification, incremental backup, recovery, and security. | manual-2026-06-11 | Indexed (BM25) |
| GNU Wget 1.25.0 Manual (`wget-1.25-manual`) | Official GNU Wget reference covering HTTP/HTTPS/FTP retrieval, recursion, mirroring, authentication, proxies, retries, and configuration. | 1.25.0-manual-2024-11-11 | Indexed (BM25) |
| Linux man-pages (`linux-man-pages`) | Official Linux kernel and C library userspace interface manual pages. | 6.18 | Indexed + semantic search |

## Technical Q And A

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Arduino Stack Exchange (`arduino-stackexchange`) | Questions and answers about Arduino hardware, firmware, sensors, communication buses, libraries, and embedded projects. | 2026-06-30-community | Indexed (BM25) |
| Ask Ubuntu Stack Exchange (`askubuntu-stackexchange`) | Questions and answers about Ubuntu installation, packages, boot, hardware, networking, administration, applications, and recovery. | 2026-06-30-community | Indexed (BM25) |
| Computer Science Stack Exchange (`cs-stackexchange`) | Questions and answers about algorithms, computability, complexity, data structures, languages, architecture, and theoretical computer science. | 2026-06-30-community | Indexed (BM25) |
| Database Administrators Stack Exchange (`dba-stackexchange`) | Questions and answers about database administration, recovery, replication, indexing, performance, and data platforms. | 2026-06-30-community | Indexed + semantic search |
| DevOps Stack Exchange (`devops-stackexchange`) | Questions and answers about continuous delivery, infrastructure automation, containers, orchestration, and DevOps operations. | 2026-06-30-community | Indexed + semantic search |
| Electrical Engineering Stack Exchange (`electronics-stackexchange`) | Questions and answers about electronics, circuits, components, embedded systems, power, measurement, and diagnostics. | 2026-06-30-community | Indexed + semantic search |
| Information Security Stack Exchange (`security-stackexchange`) | Questions and answers about applied information security, cryptography, authentication, network defense, privacy, and secure software engineering. | 2026-06-30-community | Indexed + semantic search |
| Network Engineering Stack Exchange (`networkengineering-stackexchange`) | Questions and answers about professionally managed networks, routing, switching, firewalls, wireless, and network protocols. | 2026-06-30-community | Indexed + semantic search |
| Raspberry Pi Stack Exchange (`raspberrypi-stackexchange`) | Questions and answers about Raspberry Pi hardware, Linux, GPIO, boot, networking, peripherals, and embedded projects. | 2026-06-30-community | Indexed (BM25) |
| Server Fault (`serverfault-stackexchange`) | Questions and answers about managing production servers, networks, storage, virtualization, security, and infrastructure operations. | 2026-06-30-community | Indexed + semantic search |
| Signal Processing Stack Exchange (`dsp-stackexchange`) | Questions and answers about digital signal processing, filters, transforms, sampling, estimation, communications, and implementation. | 2026-06-30-community | Indexed (BM25) |
| Software Engineering Stack Exchange (`softwareengineering-stackexchange`) | Questions and answers about software architecture, design, development process, testing, requirements, and engineering practice. | 2026-06-30-community | Indexed (BM25) |
| Super User Stack Exchange (`superuser-stackexchange`) | Questions and answers about desktop operating systems, applications, storage, networking, hardware, recovery, and power-user troubleshooting. | 2026-06-30-community | Indexed (BM25) |
| Unix & Linux Stack Exchange (`unix-stackexchange`) | Questions and answers about Unix and Linux administration, shells, storage, boot, permissions, networking, and recovery. | 2026-06-30-community | Indexed + semantic search |

## UI Framework Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Apple SwiftUI Documentation Snapshot (`swiftui-docs-20260820`) | Official SwiftUI framework overview, concepts, protocols, views, modifiers, controls, layout, navigation, data flow, graphics, animation, accessibility, and platform integration documentation. | official Markdown publication snapshot acquired 2026-08-20 | Indexed (BM25) |

## Web Framework Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Angular Documentation Snapshot (`angular-docs-20260820`) | Official Angular guides, APIs, CLI, best practices, accessibility, security, and error reference. | 2026-08-20 commit d609cf6e0908b7e3c39bc21dd1c6e1457591e3d6 | Indexed (BM25) |
| ASP.NET Core Documentation Snapshot (`aspnetcore-docs-20260820`) | Official ASP.NET Core guidance for Blazor, MVC, Razor Pages, APIs, security, hosting, diagnostics, gRPC, SignalR, and deployment. | 2026-08-20 commit 6885b4c487beda992335631784c1dd31b301403b | Indexed (BM25) |
| Django Documentation Snapshot (`django-docs-20260820`) | Official Django tutorials, topic guides, API references, deployment, security, and internals documentation. | 2026-08-20 commit cccc004b46f71b4e54d87b376be691a17de6b903 | Indexed (BM25) |
| FastAPI Documentation Snapshot (`fastapi-docs-20260820`) | Official FastAPI tutorials, advanced guides, deployment, security, testing, dependency injection, and API documentation. | 2026-08-20 commit c3f316b7e814667e8ee81e03a7330d00ee61e45c | Indexed (BM25) |
| Flask Documentation Snapshot (`flask-docs-20260820`) | Official Flask quickstart, tutorial, API, configuration, deployment, security, extension, and design documentation. | 2026-08-20 commit d318b683471101618febed18996405ad26462110 | Indexed (BM25) |
| Ktor Documentation Snapshot (`ktor-docs-20260820`) | Official Ktor server and client guides for configuration, plugins, networking, authentication, serialization, testing, deployment, and observability. | 2026-08-20 commit 5803616c32b5f16050a8b1ae4653afa21603796e | Indexed (BM25) |
| Laravel 13 Documentation (`laravel-docs-13`) | Official Laravel application architecture, HTTP, database, queues, security, testing, deployment, and package documentation. | 13.x commit 501e8cf7f5e69e26b3c64d1a0656cacef2b4d413 | Indexed (BM25) |
| Next.js Documentation Snapshot (`nextjs-docs-20260820`) | Official Next.js App Router, Pages Router, architecture, API, deployment, caching, and configuration documentation. | 2026-08-20 commit 14a69ef78b94c9bdb68b2f1d5d1a55599ff8022c | Indexed (BM25) |
| React Documentation Snapshot (`react-docs-20260820`) | Official React learning guides, API references, warnings, and error explanations. | 2026-08-20 commit 12d692da47e77cdc558b928fcfbaf4e71c6d0cec | Indexed (BM25) |
| Ruby on Rails Guides Snapshot (`rails-guides-20260820`) | Official Rails guides for models, controllers, views, jobs, mail, storage, security, testing, configuration, and operations. | 2026-08-20 commit 92da89741cf7e46783d7b2da64fac5293590ee57 | Indexed (BM25) |
| Spring Boot Documentation Snapshot (`spring-boot-docs-20260820`) | Official Spring Boot reference, tutorials, how-to guides, specifications, actuator, CLI, and build-plugin documentation. | 2026-08-20 commit d1e52a1be8ecb1c36852dad8d40d220830b49e26 | Indexed (BM25) |
| Vue Documentation Snapshot (`vue-docs-20260820`) | Official Vue guide, API, tutorial, examples, style guide, and terminology reference. | 2026-08-20 commit b75d188ab16bf83bd1f364a77dfd2315be8f3fa4 | Indexed (BM25) |

## Web Server Documentation

| Corpus | What it covers | Pinned version / snapshot | Local state |
|---|---|---|---|
| Apache HTTP Server 2.4.68 Documentation (`apache-httpd-2.4-docs`) | Official Apache HTTP Server administration, configuration, modules, security, TLS, authentication, proxying, logging, virtual hosting, performance, and troubleshooting documentation. | 2.4.68 | Indexed (BM25) |
| NGINX Open Source Documentation Snapshot (`nginx-docs-20260820`) | Official NGINX installation, configuration, operations, development, HTTP, stream, mail, module, directive, load-balancing, caching, TLS, QUIC, and troubleshooting documentation. | main commit df444293ce3b9761809b16313e78ea7322ce97fe, 2026-08-20 | Indexed (BM25) |

## Licensing and reproducibility

The collection mixes open licenses, government works, attribution/share-alike material, and private-reference-only documentation. Each dataset keeps its own terms and provenance. The public project should distribute the code, manifests, importers, tests, and reproducible acquisition instructions—not copyrighted corpus payloads.

The machine-readable source of truth is [`config/datasets.json`](../config/datasets.json). Wikipedia uses a separate manifest because its multistream dump and update process are specialized.
