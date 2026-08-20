from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .bm25 import plan_query, read_index_metadata, search


def _connect_read_only(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _heading_parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(">") if part.strip()]


def _citation(
    corpus: str,
    title: str,
    heading_path: list[str],
    timestamp: str | None,
    source_url: str | None,
) -> str:
    label = "Wikipedia" if corpus == "wikipedia-en" else corpus
    section = f" § {' > '.join(heading_path)}" if heading_path else ""
    revision = f" ({timestamp})" if timestamp else ""
    source = f" {source_url}" if source_url else ""
    return f"{label} — {title}{section}{revision}{source}"


def index_status(database: Path) -> dict[str, Any]:
    """Return inexpensive readiness and build metadata for a published index."""

    metadata = read_index_metadata(database)
    stat = database.stat()
    return {
        "ready": True,
        "database": str(database.resolve()),
        "database_bytes": stat.st_size,
        "schema_version": metadata.get("schema_version", 1),
        "build_id": metadata.get("build_id"),
        "built_at": metadata.get("built_at"),
        "source_corpora": metadata.get("source_corpora", ["wikipedia-en"]),
        "source_versions": metadata.get("source_versions", []),
        "document_count": metadata.get("document_count"),
        "chunk_count": metadata.get("chunk_count"),
        "tokenizer": metadata.get("tokenizer"),
        "query_configuration": metadata.get("query_configuration"),
    }


def search_documents(
    database: Path,
    query: str,
    *,
    limit: int = 8,
    mode: str = "and",
    candidate_limit: int = 160,
    allow_relaxation: bool = True,
) -> dict[str, Any]:
    """Return distinct documents with bounded query relaxation when needed.

    Strict AND remains the primary retrieval. When ``allow_relaxation`` is true
    and a query of four or more terms has no exact-title hit, leave-one-term-out
    variants are fused using RRF.
    A candidate whose title terms are contained in the original query is then
    resolved through exact-title search so agents receive its lead passage.
    This recovers from one guessed or overly specific term without degrading
    short exact entity queries into unrestricted OR searches.
    """

    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if candidate_limit < limit:
        raise ValueError("candidate_limit must be at least limit")
    original_plan = plan_query(query, mode)
    primary = search(database, query, limit=candidate_limit, mode=mode)
    variants: list[tuple[str, list[dict[str, object]], float]] = [(query, primary, 1.0)]
    relaxed = False
    if (
        allow_relaxation
        and mode == "and"
        and len(original_plan.normalized_terms) >= 4
        and not any(item.get("ranking_reason") == "exact_title" for item in primary)
    ):
        relaxed = True
        terms = original_plan.normalized_terms
        for dropped_index in range(min(len(terms), 6)):
            variant = " ".join(term for index, term in enumerate(terms) if index != dropped_index)
            variants.append((variant, search(database, variant, limit=candidate_limit, mode="and"), 0.8))

    scores: dict[str, float] = {}
    representatives: dict[str, dict[str, object]] = {}
    matched_variants: dict[str, set[str]] = {}
    for variant, candidates, weight in variants:
        seen: set[str] = set()
        document_rank = 0
        for candidate in candidates:
            document_id = str(candidate["document_id"])
            if document_id in seen:
                continue
            seen.add(document_id)
            document_rank += 1
            scores[document_id] = scores.get(document_id, 0.0) + weight / (60.0 + document_rank)
            matched_variants.setdefault(document_id, set()).add(variant)
            representatives.setdefault(document_id, candidate)

    original_terms = set(original_plan.normalized_terms)
    for document_id, representative in list(representatives.items()):
        title = str(representative["title"])
        try:
            title_terms = set(plan_query(title, "and").normalized_terms)
        except ValueError:
            continue
        if len(title_terms) < 2 or not title_terms.issubset(original_terms):
            continue
        exact = search(database, title, limit=1, mode="and")
        if exact and str(exact[0]["document_id"]) == document_id:
            promoted = dict(exact[0])
            promoted["ranking_reason"] = "relaxed_exact_title" if relaxed else "exact_title"
            representatives[document_id] = promoted
            scores[document_id] += 1.0

    ordered_ids = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
    results: list[dict[str, object]] = []
    for document_id in ordered_ids:
        item = dict(representatives[document_id])
        item["matched_query"] = item.get("query")
        item["query"] = query
        item["query_mode"] = mode
        item["fusion_score"] = scores[document_id]
        item["matched_variants"] = sorted(matched_variants[document_id])
        results.append(item)
    return {
        "query": query,
        "mode": mode,
        "ranking_unit": "document",
        "query_relaxed": relaxed,
        "variants_searched": len(variants),
        "candidate_chunks": sum(len(candidates) for _, candidates, _ in variants),
        "results": results,
    }


def retrieve_document(
    database: Path,
    document_id: str,
    *,
    chunk_offset: int = 0,
    chunk_limit: int = 20,
) -> dict[str, Any]:
    """Retrieve document metadata and an ordered, bounded page of chunks."""

    if not document_id.strip():
        raise ValueError("document_id must not be empty")
    if chunk_offset < 0:
        raise ValueError("chunk_offset must not be negative")
    if not 1 <= chunk_limit <= 200:
        raise ValueError("chunk_limit must be between 1 and 200")

    metadata = read_index_metadata(database)
    schema_version = int(metadata.get("schema_version", 1))
    connection = _connect_read_only(database)
    try:
        if schema_version >= 2:
            row = connection.execute(
                """
                SELECT document_id, corpus, title, source_url, source_version,
                       source_timestamp, license, content_hash, attributes_json
                FROM documents WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            document = dict(row)
            document["attributes"] = json.loads(document.pop("attributes_json"))
            total_chunks = connection.execute(
                "SELECT count(*) FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            chunk_rows = connection.execute(
                """
                SELECT chunk_instance_id AS chunk_id, content_id, parent_chunk_id,
                       ordinal, heading_path, text, character_count, token_count,
                       previous_chunk_id, next_chunk_id, attributes_json
                FROM chunks
                WHERE document_id = ?
                ORDER BY ordinal, row_id
                LIMIT ? OFFSET ?
                """,
                (document_id, chunk_limit, chunk_offset),
            ).fetchall()
            chunks: list[dict[str, Any]] = []
            for chunk_row in chunk_rows:
                chunk = dict(chunk_row)
                chunk["heading_path"] = _heading_parts(chunk["heading_path"])
                attributes = json.loads(chunk.pop("attributes_json"))
                chunk["attributes"] = attributes
                chunk["section_index"] = attributes.get("section_index")
                chunk["chunk_index"] = attributes.get("chunk_index")
                chunk["citation"] = _citation(
                    str(document["corpus"]),
                    str(document["title"]),
                    chunk["heading_path"],
                    document.get("source_timestamp"),
                    document.get("source_url"),
                )
                chunks.append(chunk)
        else:
            row = connection.execute(
                """
                SELECT document_id, title, source_url, revision_timestamp
                FROM documents WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            document = dict(row)
            document.update(
                {
                    "corpus": "wikipedia-en",
                    "source_version": None,
                    "source_timestamp": document.pop("revision_timestamp"),
                    "license": None,
                    "content_hash": None,
                    "attributes": {},
                }
            )
            total_chunks = connection.execute(
                "SELECT count(*) FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            chunk_rows = connection.execute(
                """
                SELECT chunk_id, heading_path, text, section_index, chunk_index
                FROM chunks
                WHERE document_id = ?
                ORDER BY section_index, chunk_index, row_id
                LIMIT ? OFFSET ?
                """,
                (document_id, chunk_limit, chunk_offset),
            ).fetchall()
            chunks = []
            for chunk_row in chunk_rows:
                chunk = dict(chunk_row)
                chunk["heading_path"] = _heading_parts(chunk["heading_path"])
                chunk["citation"] = _citation(
                    "wikipedia-en",
                    str(document["title"]),
                    chunk["heading_path"],
                    document.get("source_timestamp"),
                    document.get("source_url"),
                )
                chunks.append(chunk)
    finally:
        connection.close()

    document["citation"] = _citation(
        str(document["corpus"]),
        str(document["title"]),
        [],
        document.get("source_timestamp"),
        document.get("source_url"),
    )
    return {
        "document": document,
        "chunks": chunks,
        "pagination": {
            "offset": chunk_offset,
            "limit": chunk_limit,
            "returned": len(chunks),
            "total_chunks": total_chunks,
            "has_more": chunk_offset + len(chunks) < total_chunks,
        },
    }


def retrieve_chunk_context(
    database: Path,
    chunk_id: str,
    *,
    before: int = 1,
    after: int = 1,
) -> dict[str, Any]:
    """Retrieve a search hit and a small number of neighboring chunks.

    This is the preferred agent-facing expansion operation: it keeps context
    bounded while preserving the article sequence around an already relevant
    search result.
    """

    if not chunk_id.strip():
        raise ValueError("chunk_id must not be empty")
    if not 0 <= before <= 5:
        raise ValueError("before must be between 0 and 5")
    if not 0 <= after <= 5:
        raise ValueError("after must be between 0 and 5")

    metadata = read_index_metadata(database)
    schema_version = int(metadata.get("schema_version", 1))
    connection = _connect_read_only(database)
    try:
        if schema_version >= 2:
            anchor = connection.execute(
                "SELECT document_id, ordinal FROM chunks WHERE chunk_instance_id = ?",
                (chunk_id,),
            ).fetchone()
            ordinal = int(anchor["ordinal"]) if anchor is not None else 0
        else:
            anchor = connection.execute(
                """
                SELECT row_id, document_id, section_index, chunk_index
                FROM chunks WHERE chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
            ordinal = (
                int(
                    connection.execute(
                        """
                        SELECT count(*) FROM chunks
                        WHERE document_id = ? AND (
                            section_index < ? OR
                            (section_index = ? AND chunk_index < ?) OR
                            (section_index = ? AND chunk_index = ? AND row_id < ?)
                        )
                        """,
                        (
                            anchor["document_id"],
                            anchor["section_index"],
                            anchor["section_index"],
                            anchor["chunk_index"],
                            anchor["section_index"],
                            anchor["chunk_index"],
                            anchor["row_id"],
                        ),
                    ).fetchone()[0]
                )
                if anchor is not None
                else 0
            )
    finally:
        connection.close()
    if anchor is None:
        raise KeyError(chunk_id)

    offset = max(0, ordinal - before)
    page = retrieve_document(
        database,
        str(anchor["document_id"]),
        chunk_offset=offset,
        chunk_limit=before + after + 1,
    )
    page["context"] = {
        "anchor_chunk_id": chunk_id,
        "anchor_ordinal": ordinal,
        "before": before,
        "after": after,
    }
    return page
