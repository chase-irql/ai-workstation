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

1. Choose the most authoritative likely corpus before searching when the subject makes that clear.
   - Practical health, first aid, sanitation, and community medicine: `hesperian-english-health-guides-20260820`.
   - Device repair, disassembly, maintenance, parts, and tools: `ifixit-english-2025-12`.
   - Internet standards and protocol behavior: `rfc-editor-text`; exact assignments: `iana-protocol-registries`.
   - Programming questions: prefer the language's official versioned documentation over community answers. Use `java-se-jdk-26-docs`, `kotlin-docs-20260820`, `php-manual-en-20260820`, `ruby-4.0-docs`, or `swift-book-20260820` when the language is explicit.
   - JavaScript and browser APIs: use `mdn-javascript-20260820` for practical API/language guidance and `ecmascript-2026-spec` when normative language semantics or algorithms matter.
   - C and C++ library/language reference: use `cppreference-20250209`, while clearly identifying it as community-maintained rather than an ISO standard.
   - General encyclopedic questions: `wikipedia`.
   - Use `knowledge_index_status` to discover other exact corpus IDs rather than guessing.
2. Form a short retrieval query from two to six distinctive subject terms. Do not copy conversational scaffolding or inject an authority such as WHO unless the user requested it.
3. Call `search_knowledge`.
   - If the user names a source or corpus, pass its exact corpus ID in `corpora`.
   - If only a friendly source name is known, use `knowledge_index_status` or one broad search to discover the exact corpus ID. Never invent an ID.
   - Otherwise search across corpora and let the server route.
   - Use `retrieval="auto"` normally.
   - Use `retrieval="bm25"` for procedures, recipes, quantities, exact names, error codes, measurements, quotations, identifiers, or when the user requires CPU-only retrieval. This is mandatory for safety-sensitive quantities.
   - Use `mode="and"` with a few compatible terms. If it produces no useful evidence, shorten the query before considering another mode.
4. If a search times out, retry through `offline-knowledge` with one exact corpus, `retrieval="bm25"`, fewer query terms, and a smaller result limit. Do not switch MCP servers.
5. Read the returned evidence. Select results based on relevance, authority, source version, and direct support—not rank alone.
6. When more context is needed, call `retrieve_knowledge_context` using the selected result's `knowledge_corpus` and `chunk_id` verbatim. Prefer this over retrieving a whole document.
7. Use `retrieve_knowledge_document` only for intentional paginated reading. Pass the complete returned `document_id`, including its corpus prefix, verbatim.
8. Refine the search when evidence does not directly contain the requested fact. Never fill an evidence gap from assumption.
9. Answer from the retrieved text and preserve exact citations.

## Identifier and citation integrity

- Cite claims with each result's `citation_reference` (for example, `[S1]`). At the end, copy the corresponding `copy_ready_citations.sources[].citation_markdown` value verbatim into a Sources list.
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
- If adequate evidence is absent, say what could not be verified and stop rather than improvising.

## Tool selection

- `search_knowledge`: default entry point.
- `retrieve_knowledge_context`: preferred evidence expansion using a returned chunk ID.
- `retrieve_knowledge_document`: bounded reading only when context expansion is insufficient.
- `knowledge_index_status`: diagnostics and corpus discovery, not a required prelude to every search.

Return a concise answer with `[S#]` references followed by the server-generated `citation_markdown` source lines unless the user requests another format. A document ID alone is not a citation.
