from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .bm25 import read_index_metadata, search


SMOKE_QUERIES = (
    "Apollo 11 first humans Moon 1969",
    "Python programming language",
    "C++ standard library",
    "North African country capital Algiers",
)


def _expected_counts(input_directory: Path) -> tuple[int, int]:
    stats_path = input_directory / "extraction-stats.json"
    value = json.loads(stats_path.read_text(encoding="utf-8"))
    if not value.get("completed") or value.get("stop_reason") not in {"archive_complete", "source_complete"}:
        raise ValueError("Corpus extraction is not complete")
    counts = value.get("totals", value)
    return int(counts["documents"]), int(counts["chunks"])


def verify_database(
    database: Path,
    input_directory: Path,
    smoke_queries: Sequence[str] = SMOKE_QUERIES,
) -> dict[str, Any]:
    """Run independent count, integrity, relationship, FTS, and search checks."""

    if not database.is_file():
        raise FileNotFoundError(database)
    expected_documents, expected_chunks = _expected_counts(input_directory)
    started = time.perf_counter()
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True, timeout=30)
    try:
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        if quick_check != ["ok"]:
            raise RuntimeError(f"SQLite quick_check failed: {quick_check[:10]}")
        foreign_key_violation = connection.execute(
            "SELECT * FROM pragma_foreign_key_check LIMIT 1"
        ).fetchone()
        if foreign_key_violation is not None:
            raise RuntimeError(f"SQLite foreign-key violation: {foreign_key_violation}")
        documents = int(connection.execute("SELECT count(*) FROM documents").fetchone()[0])
        chunks = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        fts_rows = int(connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0])
    finally:
        connection.close()
    if documents != expected_documents:
        raise RuntimeError(f"Document count mismatch: {documents} != {expected_documents}")
    if chunks != expected_chunks:
        raise RuntimeError(f"Chunk count mismatch: {chunks} != {expected_chunks}")
    if fts_rows != expected_chunks:
        raise RuntimeError(f"FTS row count mismatch: {fts_rows} != {expected_chunks}")

    smoke_results: list[dict[str, Any]] = []
    for query in smoke_queries:
        query_started = time.perf_counter()
        results = search(database, query, limit=5, mode="and")
        latency_ms = (time.perf_counter() - query_started) * 1000
        if not results:
            raise RuntimeError(f"Smoke query returned no results: {query}")
        required = {
            "document_id",
            "chunk_id",
            "title",
            "heading_path",
            "source_url",
            "citation",
            "raw_score",
        }
        missing = required.difference(results[0])
        if missing:
            raise RuntimeError(f"Smoke query result is missing fields {sorted(missing)}: {query}")
        smoke_results.append(
            {
                "query": query,
                "latency_ms": round(latency_ms, 3),
                "top_document_id": results[0]["document_id"],
                "top_title": results[0]["title"],
                "citation": results[0]["citation"],
            }
        )

    metadata = read_index_metadata(database)
    if int(metadata.get("document_count", -1)) != documents:
        raise RuntimeError("Index metadata document_count mismatch")
    if int(metadata.get("chunk_count", -1)) != chunks:
        raise RuntimeError("Index metadata chunk_count mismatch")
    return {
        "verified": True,
        "database": str(database.resolve()),
        "database_bytes": database.stat().st_size,
        "documents": documents,
        "chunks": chunks,
        "fts_rows": fts_rows,
        "quick_check": "ok",
        "foreign_keys": "ok",
        "smoke_queries": smoke_results,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a completed offline RAG SQLite database")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--smoke-query",
        action="append",
        help="Corpus-specific AND-mode smoke query; repeat for multiple queries",
    )
    args = parser.parse_args()
    result = verify_database(args.database, args.input, tuple(args.smoke_query) if args.smoke_query else SMOKE_QUERIES)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
