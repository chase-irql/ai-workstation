from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .bm25 import read_index_metadata


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
