from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from .embeddings import EmbeddingProvider, OllamaEmbeddingClient, load_embedding_model_config
from .retrieval import retrieve_chunk_context, retrieve_document
from .retrieval_runtime import RETRIEVAL_MODES, RetrievalRuntime


QueryMode = Literal["and", "phrase", "exact"]
RetrievalSelection = Literal["default", "bm25", "semantic", "hybrid"]


def _bounded(value: int, name: str, minimum: int, maximum: int) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _document_results(
    runtime: RetrievalRuntime,
    query: str,
    limit: int,
    mode: QueryMode,
    retrieval: RetrievalSelection,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > 2_000:
        raise ValueError("query must not exceed 2000 characters")
    limit = _bounded(limit, "limit", 1, 20)
    return runtime.search(
        query,
        limit=limit,
        query_mode=mode,
        retrieval_mode=None if retrieval == "default" else retrieval,
        candidate_limit=min(400, max(80, limit * 20)),
    )


def create_mcp_server(
    database: Path,
    *,
    vector_directory: Path | None = None,
    provider_factory: Callable[[], EmbeddingProvider] | None = None,
    default_retrieval: str = "bm25",
    query_cache_size: int = 256,
) -> MCPServer:
    """Create an MCP server bound to one immutable, published index."""

    database = database.resolve()
    runtime = RetrievalRuntime(
        database,
        vector_directory=vector_directory,
        provider_factory=provider_factory,
        default_mode=default_retrieval,
        query_cache_size=query_cache_size,
    )
    server = MCPServer(
        "offline-wikipedia",
        title="Offline Wikipedia",
        description="Read-only BM25, semantic, and hybrid retrieval over local English Wikipedia.",
        instructions=(
            "Use search_wikipedia to find source passages; every result already contains usable "
            "evidence and a citation. Prefer retrieve_wikipedia_context with a result's chunk_id "
            "when neighboring text is needed. Use retrieve_wikipedia_document only for deliberate, "
            "small paginated reads. Never fetch an entire article. Preserve returned citations."
        ),
        version="0.5.0",
    )
    setattr(server, "_offline_retrieval_runtime", runtime)

    @server.tool(structured_output=True)
    def search_wikipedia(
        query: str,
        limit: int = 8,
        mode: QueryMode = "and",
        retrieval: RetrievalSelection = "default",
    ) -> dict[str, Any]:
        """Search cited Wikipedia evidence with the configured or explicitly selected retriever."""

        return _document_results(runtime, query, limit, mode, retrieval)

    @server.tool(structured_output=True)
    def retrieve_wikipedia_document(
        document_id: str,
        chunk_offset: int = 0,
        chunk_limit: Annotated[
            int,
            Field(description="Requested page size; safely clamped to the range 1 through 12."),
        ] = 4,
    ) -> dict[str, Any]:
        """Retrieve a small ordered page; do not use this to fetch an entire article."""

        requested_offset = chunk_offset
        requested_limit = chunk_limit
        chunk_offset = max(0, min(int(chunk_offset), 1_000_000))
        chunk_limit = max(1, min(int(chunk_limit), 12))
        result = retrieve_document(
            runtime.database,
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
    def retrieve_wikipedia_context(
        chunk_id: str,
        before: Annotated[int, Field(description="Requested preceding chunks; safely clamped to 0 through 3.")] = 1,
        after: Annotated[int, Field(description="Requested following chunks; safely clamped to 0 through 3.")] = 1,
    ) -> dict[str, Any]:
        """Expand one search hit with only its nearby chunks; preferred for focused context."""

        requested_before = before
        requested_after = after
        before = max(0, min(int(before), 3))
        after = max(0, min(int(after), 3))
        result = retrieve_chunk_context(runtime.database, chunk_id, before=before, after=after)
        result["context"]["requested_before"] = requested_before
        result["context"]["requested_after"] = requested_after
        result["context"]["clamped"] = requested_before != before or requested_after != after
        return result

    @server.tool(structured_output=True)
    def wikipedia_index_status() -> dict[str, Any]:
        """Return readiness, corpus version, counts, and build identity for the local index."""

        return {**runtime.lexical_status, "retrieval": runtime.status()}

    return server


def close_mcp_server(server: MCPServer) -> None:
    """Close lazily opened semantic resources owned by a server instance."""

    runtime = getattr(server, "_offline_retrieval_runtime", None)
    if isinstance(runtime, RetrievalRuntime):
        runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline Wikipedia MCP server over stdio.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vector-index", type=Path)
    parser.add_argument("--models", type=Path, default=Path("config/models.json"))
    parser.add_argument("--model-id")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--default-retrieval", choices=RETRIEVAL_MODES, default="bm25")
    parser.add_argument("--query-cache-size", type=int, default=256)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider_factory = None
    if args.vector_index is not None:
        config = load_embedding_model_config(args.models, args.model_id)
        provider_factory = lambda: OllamaEmbeddingClient(config, base_url=args.ollama_url)
    server = create_mcp_server(
        args.database,
        vector_directory=args.vector_index,
        provider_factory=provider_factory,
        default_retrieval=args.default_retrieval,
        query_cache_size=args.query_cache_size,
    )
    try:
        server.run(transport="stdio")
    finally:
        close_mcp_server(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
