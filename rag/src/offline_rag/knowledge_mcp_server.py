from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from .embeddings import OllamaEmbeddingClient, load_embedding_model_config
from .knowledge import KnowledgeCorpus, KnowledgeRuntime
from .retrieval_runtime import RETRIEVAL_MODES, CachedEmbeddingProvider
from .vector_index import load_vector_manifest


QueryMode = Literal["and", "phrase", "exact"]
RetrievalSelection = Literal["auto", "default", "bm25", "semantic", "hybrid"]


def create_knowledge_mcp_server(
    corpora: Sequence[KnowledgeCorpus],
    *,
    query_cache_size: int = 256,
) -> MCPServer:
    """Create the read-only, corpus-neutral knowledge MCP server."""

    runtime = KnowledgeRuntime(corpora, query_cache_size=query_cache_size)
    server = MCPServer(
        "offline-knowledge",
        title="Offline Knowledge",
        description="Read-only retrieval across independently versioned local knowledge corpora.",
        instructions=(
            "Use search_knowledge to find cited evidence across local corpora. Pass a corpus filter "
            "when the source type is known. Search results include the knowledge_corpus and chunk_id; "
            "pass both to retrieve_knowledge_context for focused neighboring evidence. Use "
            "retrieve_knowledge_document only for small paginated reads. Preserve returned citations."
        ),
        version="0.1.0",
    )
    setattr(server, "_offline_knowledge_runtime", runtime)

    @server.tool(structured_output=True)
    def search_knowledge(
        query: str,
        limit: Annotated[int, Field(description="Requested result count; clamped to 1 through 20.")] = 8,
        mode: QueryMode = "and",
        corpora: list[str] | None = None,
        retrieval: RetrievalSelection = "auto",
        rerank: bool = True,
        deduplicate: bool = True,
    ) -> dict[str, Any]:
        """Search cited evidence across all or selected offline knowledge corpora."""

        requested_limit = limit
        limit = max(1, min(int(limit), 20))
        result = runtime.search(
            query,
            limit=limit,
            mode=mode,
            corpus_ids=corpora,
            retrieval=retrieval,
            rerank=rerank,
            deduplicate=deduplicate,
        )
        result["request"] = {
            "requested_limit": requested_limit,
            "effective_limit": limit,
            "clamped": requested_limit != limit,
        }
        return result

    @server.tool(structured_output=True)
    def retrieve_knowledge_document(
        corpus: str,
        document_id: str,
        chunk_offset: int = 0,
        chunk_limit: Annotated[int, Field(description="Requested page size; clamped to 1 through 12.")] = 4,
    ) -> dict[str, Any]:
        """Retrieve a small ordered page from a known corpus and document."""

        requested_offset = chunk_offset
        requested_limit = chunk_limit
        chunk_offset = max(0, min(int(chunk_offset), 1_000_000))
        chunk_limit = max(1, min(int(chunk_limit), 12))
        result = runtime.retrieve_document(
            corpus,
            document_id,
            chunk_offset=chunk_offset,
            chunk_limit=chunk_limit,
        )
        result["request"] = {
            "requested_offset": requested_offset,
            "requested_limit": requested_limit,
            "effective_offset": chunk_offset,
            "effective_limit": chunk_limit,
            "clamped": requested_offset != chunk_offset or requested_limit != chunk_limit,
        }
        return result

    @server.tool(structured_output=True)
    def retrieve_knowledge_context(
        corpus: str,
        chunk_id: str,
        before: Annotated[int, Field(description="Requested preceding chunks; clamped to 0 through 3.")] = 1,
        after: Annotated[int, Field(description="Requested following chunks; clamped to 0 through 3.")] = 1,
    ) -> dict[str, Any]:
        """Expand a search hit with a bounded number of neighboring chunks."""

        requested_before = before
        requested_after = after
        before = max(0, min(int(before), 3))
        after = max(0, min(int(after), 3))
        result = runtime.retrieve_context(corpus, chunk_id, before=before, after=after)
        result["context"]["requested_before"] = requested_before
        result["context"]["requested_after"] = requested_after
        result["context"]["clamped"] = requested_before != before or requested_after != after
        return result

    @server.tool(structured_output=True)
    def knowledge_index_status() -> dict[str, Any]:
        """Return readiness, versions, build identities, counts, and retrieval modes."""

        return runtime.status()

    return server


def close_knowledge_mcp_server(server: MCPServer) -> None:
    runtime = getattr(server, "_offline_knowledge_runtime", None)
    if isinstance(runtime, KnowledgeRuntime):
        runtime.close()


def _mapping(values: Sequence[str], option: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        corpus_id, separator, path = value.partition("=")
        if not separator or not corpus_id.strip() or not path.strip():
            raise ValueError(f"{option} must use CORPUS=PATH: {value!r}")
        if corpus_id in result:
            raise ValueError(f"duplicate {option} corpus: {corpus_id}")
        result[corpus_id] = Path(path)
    return result


def _provider_factories(
    vector_indexes: dict[str, Path],
    *,
    models: Path,
    model_id: str | None,
    ollama_url: str,
    query_cache_size: int,
) -> dict[str, Any]:
    """Resolve the exact provider identity recorded by each vector generation.

    Corpora may deliberately use different Matryoshka dimensions. Providers
    with the same recorded model profile share one lazy query cache, while a
    global ``model_id`` remains a strict override for legacy commands.
    """

    providers: dict[str, CachedEmbeddingProvider] = {}
    factories: dict[str, Any] = {}
    for corpus_id, directory in vector_indexes.items():
        manifest = load_vector_manifest(directory)
        recorded = manifest.get("provider")
        if not isinstance(recorded, dict):
            raise ValueError(f"Semantic generation for {corpus_id!r} has no provider identity")
        recorded_model_id = recorded.get("model_id")
        if not isinstance(recorded_model_id, str) or not recorded_model_id:
            raise ValueError(f"Semantic generation for {corpus_id!r} has no provider model_id")
        selected_id = model_id or recorded_model_id
        config = load_embedding_model_config(models, selected_id)
        client = OllamaEmbeddingClient(config, base_url=ollama_url)
        if dict(client.provider_metadata) != recorded:
            raise ValueError(
                f"Semantic generation for {corpus_id!r} requires provider {recorded_model_id!r} "
                f"at {recorded.get('dimensions')} dimensions, but {selected_id!r} does not match"
            )
        provider = providers.get(selected_id)
        if provider is None:
            provider = CachedEmbeddingProvider(client, query_cache_size)
            providers[selected_id] = provider
        factories[corpus_id] = lambda resolved=provider: resolved
    return factories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the federated offline knowledge MCP server over stdio.")
    parser.add_argument("--index", action="append", required=True, metavar="CORPUS=DATABASE")
    parser.add_argument(
        "--corpus-vector",
        action="append",
        default=[],
        metavar="CORPUS=DIRECTORY",
        help="Repeatable semantic generation mapping; preferred for multi-corpus hybrid retrieval",
    )
    # Retain the original single-vector options for existing Wikipedia-only commands.
    parser.add_argument("--vector-corpus")
    parser.add_argument("--vector-index", type=Path)
    parser.add_argument("--models", type=Path, default=Path("config/models.json"))
    parser.add_argument("--model-id")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--default-vector-retrieval", choices=RETRIEVAL_MODES, default="hybrid")
    parser.add_argument("--query-cache-size", type=int, default=256)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    indexes = _mapping(args.index, "--index")
    vector_indexes = _mapping(args.corpus_vector, "--corpus-vector")
    if (args.vector_corpus is None) != (args.vector_index is None):
        raise ValueError("--vector-corpus and --vector-index must be supplied together")
    if args.vector_corpus is not None and args.vector_corpus not in indexes:
        raise ValueError("--vector-corpus must name one of the configured --index corpora")
    if args.vector_corpus is not None:
        if args.vector_corpus in vector_indexes:
            raise ValueError("A corpus cannot be configured by both legacy and repeatable vector options")
        vector_indexes[args.vector_corpus] = args.vector_index
    unknown_vectors = sorted(set(vector_indexes) - set(indexes))
    if unknown_vectors:
        raise ValueError(f"Semantic vector mappings name unknown corpora: {', '.join(unknown_vectors)}")
    provider_factories = _provider_factories(
        vector_indexes,
        models=args.models,
        model_id=args.model_id,
        ollama_url=args.ollama_url,
        query_cache_size=args.query_cache_size,
    ) if vector_indexes else {}
    corpora = [
        KnowledgeCorpus(
            corpus_id,
            database,
            vector_directory=vector_indexes.get(corpus_id),
            provider_factory=provider_factories.get(corpus_id),
            default_retrieval=args.default_vector_retrieval if corpus_id in vector_indexes else "bm25",
        )
        for corpus_id, database in indexes.items()
    ]
    server = create_knowledge_mcp_server(corpora, query_cache_size=args.query_cache_size)
    try:
        server.run(transport="stdio")
    finally:
        close_knowledge_mcp_server(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
