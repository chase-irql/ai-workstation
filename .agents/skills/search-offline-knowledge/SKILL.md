---
name: search-offline-knowledge
description: Reliably answer questions with the read-only offline-knowledge MCP and exact local citations. Use for requests involving the offline library, Knowledge Ark, RAG, Wikipedia, documentation, RFCs, manuals, textbooks, Hesperian guides, Stack Exchange, or source-backed local research. Also use whenever the user asks to search, verify, cite, or answer from locally indexed corpora.
---

# Search Offline Knowledge

Use the `offline-knowledge` MCP as the evidence source. The user should be able to ask a normal question without specifying tool arguments.

## Workflow

1. Form a short retrieval query from distinctive subject terms. Do not copy conversational scaffolding such as “tell me about.”
2. Call `search_knowledge`.
   - If the user names a source or corpus, pass its exact corpus ID in `corpora`.
   - If only a friendly source name is known, use `knowledge_index_status` or one broad search to discover the exact corpus ID. Never invent an ID.
   - Otherwise search across corpora and let the server route.
   - Use `retrieval="auto"` normally.
   - Use `retrieval="bm25"` for exact names, error codes, measurements, quotations, identifiers, or when the user requires CPU-only retrieval.
   - Use `mode="and"` with a few compatible terms. If it produces no useful evidence, shorten the query before considering another mode.
3. Read the returned evidence. Select results based on relevance, authority, source version, and direct support—not rank alone.
4. When more context is needed, call `retrieve_knowledge_context` using the selected result's `knowledge_corpus` and `chunk_id` verbatim. Prefer this over retrieving a whole document.
5. Use `retrieve_knowledge_document` only for intentional paginated reading. Pass the complete returned `document_id`, including its corpus prefix, verbatim.
6. Refine the search when evidence does not directly contain the requested fact. Never fill an evidence gap from assumption.
7. Answer from the retrieved text and preserve exact citations.

## Identifier and citation integrity

- Copy `knowledge_corpus`, `document_id`, `chunk_id`, `title`, `source_url`, page/heading, and `citation` exactly as returned.
- Never shorten, reconstruct, normalize, or manually retype an identifier or URL.
- Never remove underscores or the corpus prefix from an identifier.
- If a retrieval call fails, inspect the actual tool error and retry with values copied from the search result. Do not claim that an identifier format is wrong without evidence.
- Do not cite a passage that merely points to another page as though it contains the requested instructions. Retrieve the referenced evidence.
- Preserve source version and page information in the final answer.

## Evidence rules

- Support quantities, recipes, commands, procedures, warnings, dates, and version claims with text that explicitly contains them.
- Quote sparingly; otherwise paraphrase without changing technical meaning.
- If multiple sources disagree, report the disagreement and identify their versions.
- Do not claim the local corpus is current beyond its recorded source version.
- For medical, legal, electrical, mechanical, or other safety-sensitive material, distinguish source-backed reference information from current professional guidance. Do not extrapolate missing steps or measurements.
- If adequate evidence is absent, say what could not be verified and stop rather than improvising.

## Tool selection

- `search_knowledge`: default entry point.
- `retrieve_knowledge_context`: preferred evidence expansion using a returned chunk ID.
- `retrieve_knowledge_document`: bounded reading only when context expansion is insufficient.
- `knowledge_index_status`: diagnostics and corpus discovery, not a required prelude to every search.

Return a concise answer followed by exact source citations unless the user requests another format.
