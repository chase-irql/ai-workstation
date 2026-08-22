---
name: search-offline-knowledge
description: Reliably answer questions with the read-only offline-knowledge MCP and exact local citations. Use for requests involving the offline library, Knowledge Ark, RAG, Wikipedia, documentation, RFCs, manuals, textbooks, Hesperian guides, Stack Exchange, or source-backed local research. Also use whenever the user asks to search, verify, cite, or answer from locally indexed corpora.
---

# Search Offline Knowledge

Use the `offline-knowledge` MCP as the evidence source. The user should be able to ask a normal question without specifying tool arguments.

Do not call the legacy `offline-wikipedia` MCP or silently switch to another
knowledge source. A timeout from `offline-knowledge` is a reason to narrow and
retry the query, not permission to bypass it.

## Workflow

The first knowledge-tool call for a question must be `search_knowledge`. Never call either retrieval tool with an identifier recalled from model memory, copied from the user's prose, or inferred from a title, URL, or PMID.

1. Choose the most authoritative likely corpus before searching when the subject makes that clear.
   - Practical health, first aid, sanitation, and community medicine: `hesperian-english-health-guides-20260820`.
   - Device repair, disassembly, maintenance, parts, and tools: `ifixit-english-2025-12`.
   - Internet standards and protocol behavior: `rfc-editor-text`; exact assignments: `iana-protocol-registries`.
   - Programming questions: prefer the language's official versioned documentation over community answers. Use `java-se-jdk-26-docs`, `kotlin-docs-20260820`, `php-manual-en-20260820`, `ruby-4.0-docs`, or `swift-book-20260820` when the language is explicit.
   - JavaScript and browser APIs: use `mdn-javascript-20260820` for practical API/language guidance and `ecmascript-2026-spec` when normative language semantics or algorithms matter.
   - C and C++ library/language reference: use `cppreference-20250209`, while clearly identifying it as community-maintained rather than an ISO standard.
   - Biomedical papers, article titles, PMIDs, abstracts, authors, journals, MeSH terms, and published study findings: `pubmed-baseline-2026`.
   - General encyclopedic questions: `wikipedia`.
   - Use `knowledge_index_status` to discover other exact corpus IDs rather than guessing.
2. Form a short retrieval query from two to six distinctive subject terms. Do not copy conversational scaffolding or inject an authority such as WHO unless the user requested it.
   - For a named publication, begin with distinctive words from its title. Omit an author, year, journal, and question wording unless those terms are needed to distinguish the work; they may be metadata rather than searchable passage text.
3. Call `search_knowledge`.
   - If the user names a source or corpus, pass its exact corpus ID in `corpora`.
   - If only a friendly source name is known, use `knowledge_index_status` or one broad search to discover the exact corpus ID. Never invent an ID.
   - Otherwise search across corpora and let the server route.
   - Use `retrieval="auto"` normally.
   - Use `retrieval="bm25"` for procedures, recipes, quantities, exact names, error codes, measurements, quotations, identifiers, or when the user requires CPU-only retrieval. This is mandatory for safety-sensitive quantities.
   - Use `retrieval="bm25"` with `corpora=["pubmed-baseline-2026"]` for a named biomedical paper, PMID, title, abstract, author, or literature finding. PubMed has no published semantic generation yet; a broad hybrid search only adds latency.
   - Use `mode="exact"` only for a short literal phrase known to occur in the source. Do not put a conversational question, author/year description, or an entire inferred title into exact mode.
   - Use `mode="and"` with a few compatible terms. If it produces no useful evidence, shorten the query before considering another mode.
4. If a search times out, retry through `offline-knowledge` with one exact corpus, `retrieval="bm25"`, fewer query terms, and a smaller result limit. Do not switch MCP servers.
   - If a corpus-filtered search returns zero results, keep the same corpus and remove likely metadata or inferred wording. Do not broaden to every corpus unless the user asked for a cross-source search.
5. Read the returned evidence. Select results based on relevance, authority, source version, and direct support—not rank alone.
   - If a corpus-filtered result directly supports the question, use it. Do not issue a redundant unfiltered search merely to confirm it; broaden only when the evidence is genuinely insufficient.
   - For PubMed questions about a publication's findings, limitations, methods, or conclusions, require evidence whose `heading_path` is `Abstract`. Treat an `Indexing` chunk as discovery metadata only. If the selected PubMed result is `Indexing`, retrieve the preceding context or read the document from chunk offset 0 to locate the abstract before answering. Do not infer study findings from MeSH terms, publication types, or chemicals.
6. When more context is needed, call `retrieve_knowledge_context` using the selected result's `knowledge_corpus` and `chunk_id` verbatim. Prefer this over retrieving a whole document. Do not substitute the result's internal `corpus` field; routing uses `knowledge_corpus`.
7. Use `retrieve_knowledge_document` only for intentional paginated reading after a successful search. Pass the complete returned `document_id`, including its corpus prefix, verbatim. Never call retrieval first, and never use a title, PMID label, URL, or guessed text as a document ID.
8. Refine the search when evidence does not directly contain the requested fact. Never fill an evidence gap from assumption.
9. Answer from the retrieved text and preserve exact citations.
10. Before finalizing, check every part of the user's question against the selected evidence. Do not omit a requested mechanism, result, limitation, implication, or use when the passage directly supports it.

## Identifier and citation integrity

- Cite claims with each result's `citation_reference` (for example, `[S1]`). At the end, copy the corresponding `copy_ready_citations.sources[].citation_markdown` value verbatim into a Sources list.
- Do not finish after emitting inline `[S#]` markers. A sourced answer is incomplete until the final Sources list contains every cited server-generated `citation_markdown` line and its URL.
- Cite only evidence actually used in the answer. Every `[S#]` appearing in prose must have its matching `citation_markdown` line in the final Sources list; never emit dangling references.
- Treat `citation_markdown` as an opaque, server-generated artifact. Do not regenerate its label, URL, underscores, punctuation, or path from any other field.
- Copy `knowledge_corpus`, `document_id`, `chunk_id`, `title`, `source_url`, page/heading, and `citation` exactly as returned.
- Never shorten, reconstruct, normalize, or manually retype an identifier or URL.
- Never remove underscores or the corpus prefix from an identifier.
- If a retrieval call fails, inspect the actual tool error and retry with values copied from the search result. Do not claim that an identifier format is wrong without evidence.
- Do not cite a passage that merely points to another page as though it contains the requested instructions. Retrieve the referenced evidence.
- Preserve source version and page information in the final answer.

## Evidence rules

- Support quantities, recipes, commands, procedures, warnings, dates, and version claims with text that explicitly contains them.
- Verify every reported quantity digit-for-digit against a directly supporting passage. Treat flattened tables with run-together columns as ambiguous; find a clean prose passage or another authoritative local source instead.
- Prefer numbered, sequential prose over visual tables whenever a procedure has multiple methods. Do not transfer alternatives, parentheticals, warnings, or preparation steps from one method to another.
- Before answering a safety-sensitive procedure, verify separately that each ingredient, amount, unit, alternative, and action occurs within the same method-specific evidence block. If that association is unclear, search again or report that it could not be verified.
- When evidence contains mutually exclusive methods, select one complete method-specific result and keep its steps isolated. Do not combine alternatives into one synthesized procedure.
- If the first evidence uses a different authoritative term for the user's subject but does not contain the requested steps, refine the query with that source term. Do not rely on a question-specific canned query.
- Prefer results marked `evidence_kind="procedure_method"` for procedural answers. Each method described in the final answer must be supported by its own method-specific evidence block. If method-specific evidence is unavailable, state that the association could not be verified rather than combining a full-page presentation.
- Quote sparingly; otherwise paraphrase without changing technical meaning.
- If multiple sources disagree, report the disagreement and identify their versions.
- Do not claim the local corpus is current beyond its recorded source version.
- For medical, legal, electrical, mechanical, or other safety-sensitive material, distinguish source-backed reference information from current professional guidance. Do not extrapolate missing steps or measurements.
- For practical medical instructions, prefer the applicable Hesperian guide over Wikipedia when it contains the requested procedure.
- Treat PubMed as bibliographic evidence, not a clinical-guidance source. Describe claims as findings reported by the retrieved publication, preserve the PMID citation, and do not convert one abstract into current medical advice. For a named paper or literature-summary request, constrain the first search to `pubmed-baseline-2026`; for practical treatment instructions, use the applicable guidance corpus instead.
- If adequate evidence is absent, say what could not be verified and stop rather than improvising.

## Tool selection

- `search_knowledge`: default entry point.
- `retrieve_knowledge_context`: preferred evidence expansion using a returned chunk ID.
- `retrieve_knowledge_document`: bounded reading only when context expansion is insufficient.
- `knowledge_index_status`: diagnostics and corpus discovery, not a required prelude to every search.

Return a concise answer with `[S#]` references followed by the server-generated `citation_markdown` source lines unless the user requests another format. A document ID alone is not a citation.
