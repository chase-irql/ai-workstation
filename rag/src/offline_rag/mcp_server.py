from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer

from .bm25 import search
from .retrieval import index_status, retrieve_document


QueryMode = Literal["and", "or", "phrase", "exact"]


def _bounded(value: int, name: str, minimum: int, maximum: int) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _document_results(database: Path, query: str, limit: int, mode: QueryMode) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > 2_000:
        raise ValueError("query must not exceed 2000 characters")
    limit = _bounded(limit, "limit", 1, 20)
    started = time.perf_counter()
    candidates = search(database, query, limit=min(400, limit * 20), mode=mode)
    results: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for candidate in candidates:
        document_id = str(candidate["document_id"])
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        results.append(candidate)
        if len(results) == limit:
            break
    return {
        "query": query,
        "mode": mode,
        "ranking_unit": "document",
        "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
        "results": results,
    }


def create_mcp_server(database: Path) -> MCPServer:
    """Create an MCP server bound to one immutable, published index."""

    database = database.resolve()
    index_status(database)
    server = MCPServer(
        "offline-wikipedia",
        title="Offline Wikipedia",
        description="Read-only retrieval over the local English Wikipedia SQLite index.",
        instructions=(
            "Use search_wikipedia to find source passages. Use retrieve_wikipedia_document "
            "when more context from a cited document is needed. Preserve returned citations."
        ),
        version="0.3.0",
    )

    @server.tool(structured_output=True)
    def search_wikipedia(query: str, limit: int = 8, mode: QueryMode = "and") -> dict[str, Any]:
        """Search offline English Wikipedia and return distinct cited documents."""

        return _document_results(database, query, limit, mode)

    @server.tool(structured_output=True)
    def retrieve_wikipedia_document(
        document_id: str,
        chunk_offset: int = 0,
        chunk_limit: int = 10,
    ) -> dict[str, Any]:
        """Retrieve ordered source chunks for a Wikipedia document ID from search results."""

        _bounded(chunk_offset, "chunk_offset", 0, 1_000_000)
        _bounded(chunk_limit, "chunk_limit", 1, 50)
        return retrieve_document(
            database,
            document_id,
            chunk_offset=chunk_offset,
            chunk_limit=chunk_limit,
        )

    @server.tool(structured_output=True)
    def wikipedia_index_status() -> dict[str, Any]:
        """Return readiness, corpus version, counts, and build identity for the local index."""

        return index_status(database)

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline Wikipedia MCP server over stdio.")
    parser.add_argument("--database", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    create_mcp_server(args.database).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
