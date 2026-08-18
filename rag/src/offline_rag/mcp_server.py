from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from .retrieval import index_status, retrieve_chunk_context, retrieve_document, search_documents


QueryMode = Literal["and", "phrase", "exact"]


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
    response = search_documents(
        database,
        query,
        limit=limit,
        mode=mode,
        candidate_limit=min(400, max(80, limit * 20)),
    )
    response["latency_ms"] = round((time.perf_counter() - started) * 1_000, 3)
    return response


def create_mcp_server(database: Path) -> MCPServer:
    """Create an MCP server bound to one immutable, published index."""

    database = database.resolve()
    index_status(database)
    server = MCPServer(
        "offline-wikipedia",
        title="Offline Wikipedia",
        description="Read-only retrieval over the local English Wikipedia SQLite index.",
        instructions=(
            "Use search_wikipedia to find source passages; every result already contains usable "
            "evidence and a citation. Prefer retrieve_wikipedia_context with a result's chunk_id "
            "when neighboring text is needed. Use retrieve_wikipedia_document only for deliberate, "
            "small paginated reads. Never fetch an entire article. Preserve returned citations."
        ),
        version="0.4.0",
    )

    @server.tool(structured_output=True)
    def search_wikipedia(query: str, limit: int = 8, mode: QueryMode = "and") -> dict[str, Any]:
        """Search offline English Wikipedia and return distinct cited documents."""

        return _document_results(database, query, limit, mode)

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
            database,
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
        result = retrieve_chunk_context(database, chunk_id, before=before, after=after)
        result["context"]["requested_before"] = requested_before
        result["context"]["requested_after"] = requested_after
        result["context"]["clamped"] = requested_before != before or requested_after != after
        return result

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
