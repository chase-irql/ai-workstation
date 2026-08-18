from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from .bm25 import read_index_metadata
from .embeddings import EmbeddingProvider, OllamaEmbeddingClient, load_embedding_model_config
from .evaluate import evaluate, evaluate_retriever
from .retrieval import search_documents


VECTOR_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
BUILD_STATE_NAME = ".build-state.json"
BUILD_STATE_SCHEMA_VERSION = 1
VECTOR_METADATA_SCHEMA_VERSION = 2


METADATA_SCHEMA = """
CREATE TABLE vector_documents (
    vector_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    corpus TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    source_version TEXT,
    source_timestamp TEXT,
    lead_chunk_id TEXT NOT NULL,
    heading_path_json TEXT NOT NULL,
    lead_text TEXT NOT NULL
);
CREATE INDEX vector_documents_document_id_idx ON vector_documents(document_id);
CREATE TABLE vector_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


VECTOR_CONTENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vector_content (
    vector_id INTEGER PRIMARY KEY,
    embedding_text_sha256 TEXT NOT NULL,
    reused_from_generation TEXT,
    reused_from_vector_id INTEGER
);
CREATE INDEX IF NOT EXISTS vector_content_sha256_idx ON vector_content(embedding_text_sha256);
"""


@dataclass(frozen=True)
class DocumentEmbeddingRecord:
    document_id: str
    corpus: str
    title: str
    source_url: str | None
    source_version: str | None
    source_timestamp: str | None
    lead_chunk_id: str
    heading_path: tuple[str, ...]
    lead_text: str
    embedding_text: str


def embedding_text_sha256(text: str) -> str:
    """Identify the exact text representation supplied to the embedding model."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _heading_parts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(">") if part.strip())


def _citation(record: Mapping[str, Any]) -> str:
    corpus = str(record["corpus"])
    label = "Wikipedia" if corpus == "wikipedia-en" else corpus
    headings = record.get("heading_path") or []
    section = f" § {' > '.join(str(part) for part in headings)}" if headings else ""
    revision = f" ({record['source_timestamp']})" if record.get("source_timestamp") else ""
    source = f" {record['source_url']}" if record.get("source_url") else ""
    return f"{label} — {record['title']}{section}{revision}{source}"


def _connect_read_only(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    return connection


def iter_document_embedding_records(
    database: Path,
    *,
    max_chunks: int = 2,
    max_characters: int = 8_000,
    start_after_document_id: str | None = None,
) -> Iterator[DocumentEmbeddingRecord]:
    """Stream title and leading article text without loading the corpus into memory."""

    if max_chunks < 1:
        raise ValueError("max_chunks must be positive")
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    metadata = read_index_metadata(database)
    schema_version = int(metadata.get("schema_version", 1))
    connection = _connect_read_only(database)
    try:
        if schema_version >= 2:
            rows = connection.execute(
                """
                SELECT d.document_id, d.corpus, d.title, d.source_url, d.source_version,
                       d.source_timestamp, c.chunk_instance_id, c.heading_path, c.text, c.ordinal
                FROM documents d INDEXED BY sqlite_autoindex_documents_1
                JOIN chunks c INDEXED BY chunks_document_id_idx ON c.document_id = d.document_id
                WHERE c.ordinal < ? AND d.document_id > ?
                ORDER BY d.document_id
                """,
                (max_chunks, start_after_document_id or ""),
            )
        else:
            rows = connection.execute(
                """
                SELECT d.document_id, 'wikipedia-en' AS corpus, d.title, d.source_url,
                       NULL AS source_version, d.revision_timestamp AS source_timestamp,
                       c.chunk_id AS chunk_instance_id, c.heading_path, c.text,
                       row_number() OVER (
                           PARTITION BY c.document_id
                           ORDER BY c.section_index, c.chunk_index, c.row_id
                       ) - 1 AS ordinal
                FROM documents d
                JOIN chunks c ON c.document_id = d.document_id
                WHERE d.document_id > ?
                ORDER BY d.document_id, c.section_index, c.chunk_index, c.row_id
                """,
                (start_after_document_id or "",),
            )
        current_id: str | None = None
        document: dict[str, Any] | None = None
        chunks: list[tuple[int, str]] = []
        lead_ordinal: int | None = None
        for row in rows:
            document_id = str(row["document_id"])
            if current_id is not None and document_id != current_id:
                assert document is not None
                combined = "\n\n".join(text for _, text in sorted(chunks))[:max_characters]
                yield DocumentEmbeddingRecord(embedding_text=f"{document['title']}\n\n{combined}", **document)
                chunks = []
            if document_id != current_id:
                current_id = document_id
                lead_ordinal = int(row["ordinal"])
                document = {
                    "document_id": document_id,
                    "corpus": str(row["corpus"]),
                    "title": str(row["title"]),
                    "source_url": row["source_url"],
                    "source_version": row["source_version"],
                    "source_timestamp": row["source_timestamp"],
                    "lead_chunk_id": str(row["chunk_instance_id"]),
                    "heading_path": _heading_parts(str(row["heading_path"])),
                    "lead_text": str(row["text"]),
                }
            ordinal = int(row["ordinal"])
            if lead_ordinal is None or ordinal < lead_ordinal:
                assert document is not None
                lead_ordinal = ordinal
                document["lead_chunk_id"] = str(row["chunk_instance_id"])
                document["heading_path"] = _heading_parts(str(row["heading_path"]))
                document["lead_text"] = str(row["text"])
            if ordinal < max_chunks:
                chunks.append((ordinal, str(row["text"])))
        if document is not None:
            combined = "\n\n".join(text for _, text in sorted(chunks))[:max_characters]
            yield DocumentEmbeddingRecord(embedding_text=f"{document['title']}\n\n{combined}", **document)
    finally:
        connection.close()


def _batched(values: Iterable[DocumentEmbeddingRecord], size: int) -> Iterator[list[DocumentEmbeddingRecord]]:
    if size < 1:
        raise ValueError("batch_size must be positive")
    batch: list[DocumentEmbeddingRecord] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _embedded_batches(
    values: Iterable[DocumentEmbeddingRecord],
    provider: EmbeddingProvider,
    *,
    batch_size: int,
    workers: int,
) -> Iterator[tuple[list[DocumentEmbeddingRecord], np.ndarray]]:
    """Embed bounded batches concurrently while yielding them in source order."""

    if workers < 1:
        raise ValueError("embedding_workers must be positive")
    batches = _batched(values, batch_size)
    if workers == 1:
        for batch in batches:
            yield batch, provider.embed_documents([record.embedding_text for record in batch])
        return

    pending: deque[tuple[list[DocumentEmbeddingRecord], Future[np.ndarray]]] = deque()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="embedding") as executor:
        for batch in batches:
            future = executor.submit(provider.embed_documents, [record.embedding_text for record in batch])
            pending.append((batch, future))
            if len(pending) >= workers:
                first_batch, first_future = pending.popleft()
                yield first_batch, first_future.result()
        while pending:
            batch, future = pending.popleft()
            yield batch, future.result()


class _VectorReuseSource:
    """Read compatible vectors from a previously published generation in bounded batches."""

    def __init__(
        self,
        directory: Path,
        provider: EmbeddingProvider,
        content_configuration: Mapping[str, int],
        *,
        verify_checksums: bool,
    ) -> None:
        self.directory = directory.resolve()
        self.manifest = load_vector_manifest(self.directory)
        if int(self.manifest["dimensions"]) != provider.dimensions:
            raise ValueError("Reuse generation embedding dimensions do not match the selected provider")
        if self.manifest.get("provider") != dict(provider.provider_metadata):
            raise ValueError("Reuse generation embedding provider does not match the selected provider")
        if self.manifest.get("content_configuration") != dict(content_configuration):
            raise ValueError("Reuse generation content configuration does not match the requested configuration")
        if verify_checksums:
            verify_vector_index(self.directory)
        self.generation = str(self.manifest["generation"])
        self.manifest_path = self.directory / MANIFEST_NAME
        self.faiss_path = self.directory / str(self.manifest["files"]["faiss"]["name"])
        self.metadata_path = self.directory / str(self.manifest["files"]["metadata"]["name"])
        self.initial_file_stats = self._file_stats()
        self.index = faiss.read_index(str(self.faiss_path))
        self.connection = _connect_read_only(self.metadata_path)
        self.has_fingerprints = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vector_content'"
        ).fetchone() is not None
        if not self.has_fingerprints and int(content_configuration["max_chunks"]) != 1:
            self.close()
            raise ValueError(
                "Legacy reuse generations without representation fingerprints are safe only with max_chunks=1"
            )
        self.max_characters = int(content_configuration["max_characters"])

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "generation": self.generation,
            "document_count": int(self.manifest["document_count"]),
            "source_build_id": self.manifest.get("source_build_id"),
            "manifest_sha256": _sha256(self.manifest_path),
            "faiss_sha256": self.manifest["files"]["faiss"].get("sha256"),
            "metadata_sha256": self.manifest["files"]["metadata"].get("sha256"),
            "file_stats": self.initial_file_stats,
        }

    def assert_unchanged(self) -> None:
        current = self._file_stats()
        if current != self.initial_file_stats:
            raise RuntimeError("Reuse generation changed during semantic index construction")

    def _file_stats(self) -> dict[str, list[int]]:
        values: dict[str, list[int]] = {}
        for path in (self.manifest_path, self.faiss_path, self.metadata_path):
            stat = path.stat()
            values[path.name] = [stat.st_size, stat.st_mtime_ns]
        return values

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None  # type: ignore[assignment]
        self.index = None  # type: ignore[assignment]

    def resolve(
        self,
        records: Sequence[DocumentEmbeddingRecord],
        dimensions: int,
    ) -> tuple[np.ndarray, list[int], list[int | None]]:
        """Return reused vectors, positions still requiring embedding, and their source IDs."""

        document_ids = [record.document_id for record in records]
        placeholders = ",".join("?" for _ in document_ids)
        fingerprint_column = "vc.embedding_text_sha256" if self.has_fingerprints else "NULL"
        fingerprint_join = "LEFT JOIN vector_content vc ON vc.vector_id = vd.vector_id" if self.has_fingerprints else ""
        rows = self.connection.execute(
            f"""
            SELECT vd.vector_id, vd.document_id, vd.title, vd.lead_text,
                   {fingerprint_column} AS embedding_text_sha256
            FROM vector_documents vd
            {fingerprint_join}
            WHERE vd.document_id IN ({placeholders})
            """,
            document_ids,
        ).fetchall()
        prior = {str(row["document_id"]): row for row in rows}
        vectors = np.empty((len(records), dimensions), dtype=np.float32)
        missing: list[int] = []
        reused_from: list[int | None] = [None] * len(records)
        reused_positions: list[int] = []
        reused_ids: list[int] = []
        for position, record in enumerate(records):
            row = prior.get(record.document_id)
            if row is None:
                missing.append(position)
                continue
            prior_fingerprint = row["embedding_text_sha256"]
            if prior_fingerprint is None:
                prior_text = f"{row['title']}\n\n{str(row['lead_text'])[:self.max_characters]}"
                prior_fingerprint = embedding_text_sha256(prior_text)
            if str(prior_fingerprint) != embedding_text_sha256(record.embedding_text):
                missing.append(position)
                continue
            vector_id = int(row["vector_id"])
            reused_positions.append(position)
            reused_ids.append(vector_id)
            reused_from[position] = vector_id
        if reused_ids:
            reconstructed = self.index.reconstruct_batch(np.asarray(reused_ids, dtype=np.int64))
            vectors[np.asarray(reused_positions, dtype=np.int64)] = np.asarray(reconstructed, dtype=np.float32)
        return vectors, missing, reused_from


def _reuse_aware_batches(
    values: Iterable[DocumentEmbeddingRecord],
    provider: EmbeddingProvider,
    reuse: _VectorReuseSource,
    *,
    batch_size: int,
    workers: int,
) -> Iterator[tuple[list[DocumentEmbeddingRecord], np.ndarray, list[int | None]]]:
    """Reuse matching rows and concurrently embed only the misses, preserving source order."""

    if workers < 1:
        raise ValueError("embedding_workers must be positive")
    pending: deque[
        tuple[list[DocumentEmbeddingRecord], np.ndarray, list[int], list[int | None], Future[np.ndarray] | None]
    ] = deque()

    def finish(
        item: tuple[
            list[DocumentEmbeddingRecord], np.ndarray, list[int], list[int | None], Future[np.ndarray] | None
        ],
    ) -> tuple[list[DocumentEmbeddingRecord], np.ndarray, list[int | None]]:
        batch, vectors, missing, reused_from, future = item
        if future is not None:
            embedded = future.result()
            if embedded.shape != (len(missing), provider.dimensions):
                raise RuntimeError(f"Embedding provider returned an unexpected shape: {embedded.shape}")
            vectors[np.asarray(missing, dtype=np.int64)] = embedded
        return batch, np.ascontiguousarray(vectors, dtype=np.float32), reused_from

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="embedding") as executor:
        for batch in _batched(values, batch_size):
            vectors, missing, reused_from = reuse.resolve(batch, provider.dimensions)
            future = None
            if missing:
                future = executor.submit(
                    provider.embed_documents,
                    [batch[position].embedding_text for position in missing],
                )
            pending.append((batch, vectors, missing, reused_from, future))
            if len(pending) >= workers:
                yield finish(pending.popleft())
        while pending:
            yield finish(pending.popleft())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _safe_local_path(directory: Path, name: object) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError(f"Unsafe vector build filename: {name!r}")
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise ValueError(f"Vector build file escapes its directory: {name!r}")
    return path


def _load_build_state(directory: Path) -> dict[str, Any] | None:
    path = directory / BUILD_STATE_NAME
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != BUILD_STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported semantic build checkpoint: {path}")
    for key in ("raw_vectors_file", "metadata_file", "final_faiss_file", "final_metadata_file"):
        _safe_local_path(directory, value.get(key))
    return value


def _remove_build_checkpoint(directory: Path, state: Mapping[str, Any]) -> None:
    """Remove only files named by a validated semantic build checkpoint."""

    for key in ("raw_vectors_file", "metadata_file", "final_faiss_file", "final_metadata_file"):
        path = _safe_local_path(directory, state.get(key))
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        (directory / BUILD_STATE_NAME).unlink()
    except FileNotFoundError:
        pass


def _checkpoint_build(
    directory: Path,
    state: Mapping[str, Any],
    raw_stream: Any,
    connection: sqlite3.Connection,
    count: int,
    last_document_id: str | None,
) -> dict[str, Any]:
    """Durably commit raw vectors before publishing the matching metadata count."""

    raw_stream.flush()
    os.fsync(raw_stream.fileno())
    connection.commit()
    updated = {
        **state,
        "checkpointed_at": datetime.now(timezone.utc).isoformat(),
        "completed_documents": count,
        "last_document_id": last_document_id,
        "raw_vector_bytes": count * int(state["dimensions"]) * np.dtype(np.float32).itemsize,
    }
    _atomic_write_json(directory / BUILD_STATE_NAME, updated)
    return updated


def _reconcile_build_checkpoint(
    directory: Path,
    state: Mapping[str, Any],
) -> tuple[sqlite3.Connection, Any, int, str | None, dict[str, Any]]:
    """Roll raw vectors and SQLite metadata back to their common durable prefix."""

    raw_path = _safe_local_path(directory, state["raw_vectors_file"])
    metadata_path = _safe_local_path(directory, state["metadata_file"])
    final_metadata = _safe_local_path(directory, state["final_metadata_file"])
    if not metadata_path.exists() and final_metadata.exists():
        os.replace(final_metadata, metadata_path)
    if not metadata_path.exists() and int(state.get("completed_documents", 0)) == 0:
        connection = sqlite3.connect(metadata_path)
        connection.executescript(METADATA_SCHEMA)
        connection.commit()
        connection.close()
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Semantic checkpoint metadata is missing: {metadata_path}")
    if not raw_path.exists():
        raw_path.touch()
    connection = sqlite3.connect(metadata_path)
    raw_stream = raw_path.open("r+b")
    try:
        dimensions = int(state["dimensions"])
        bytes_per_vector = dimensions * np.dtype(np.float32).itemsize
        raw_size = raw_path.stat().st_size
        complete_raw_vectors = raw_size // bytes_per_vector
        metadata_count = int(connection.execute("SELECT count(*) FROM vector_documents").fetchone()[0])
        consistent_count = min(complete_raw_vectors, metadata_count)
        connection.execute("DELETE FROM vector_documents WHERE vector_id >= ?", (consistent_count,))
        connection.commit()
        raw_stream.truncate(consistent_count * bytes_per_vector)
        raw_stream.seek(0, os.SEEK_END)
        row = connection.execute(
            "SELECT document_id FROM vector_documents WHERE vector_id = ?",
            (consistent_count - 1,),
        ).fetchone()
        last_document_id = str(row[0]) if row is not None else None
        updated = _checkpoint_build(
            directory,
            state,
            raw_stream,
            connection,
            consistent_count,
            last_document_id,
        )
        return connection, raw_stream, consistent_count, last_document_id, updated
    except BaseException:
        raw_stream.close()
        connection.close()
        raise


def load_vector_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != VECTOR_SCHEMA_VERSION:
        raise ValueError(f"Unsupported vector manifest: {path}")
    files = value.get("files")
    if not isinstance(files, Mapping):
        raise ValueError(f"Vector manifest has no files object: {path}")
    for key in ("faiss", "metadata"):
        item = files.get(key)
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise ValueError(f"Vector manifest has invalid {key} file metadata")
        candidate = (directory / str(item["name"])).resolve()
        if candidate.parent != directory.resolve() or not candidate.is_file():
            raise FileNotFoundError(candidate)
        if int(item.get("bytes", -1)) != candidate.stat().st_size:
            raise ValueError(f"Vector generation file size mismatch: {candidate}")
    return value


def verify_vector_index(
    directory: Path,
    *,
    database: Path | None = None,
    verify_checksums: bool = True,
) -> dict[str, Any]:
    """Independently verify a published vector generation and optional source binding."""

    manifest = load_vector_manifest(directory)
    files = manifest["files"]
    if verify_checksums:
        for key in ("faiss", "metadata"):
            path = directory / str(files[key]["name"])
            actual = _sha256(path)
            if actual != files[key].get("sha256"):
                raise ValueError(f"Vector generation checksum mismatch: {path}")
    index_path = directory / str(files["faiss"]["name"])
    metadata_path = directory / str(files["metadata"]["name"])
    count = int(manifest["document_count"])
    dimensions = int(manifest["dimensions"])
    _validate_generation(index_path, metadata_path, count, dimensions)

    source_verified = False
    if database is not None:
        if not database.is_file():
            raise FileNotFoundError(database)
        stat = database.stat()
        if str(database.resolve()) != str(manifest.get("source_database")):
            raise ValueError("Vector generation source database path mismatch")
        if stat.st_size != int(manifest.get("source_database_bytes", -1)):
            raise ValueError("Vector generation source database size mismatch")
        source_metadata = read_index_metadata(database)
        if source_metadata.get("build_id") != manifest.get("source_build_id"):
            raise ValueError("Vector generation source build ID mismatch")
        connection = _connect_read_only(database)
        try:
            searchable = int(connection.execute("SELECT count(DISTINCT document_id) FROM chunks").fetchone()[0])
        finally:
            connection.close()
        if searchable != count:
            raise ValueError(f"Source searchable-document count mismatch: expected {count}, found {searchable}")
        source_verified = True
    return {
        "verified": True,
        "directory": str(directory.resolve()),
        "generation": manifest["generation"],
        "documents": count,
        "dimensions": dimensions,
        "checksums_verified": verify_checksums,
        "source_verified": source_verified,
    }


def _metadata_rows(records: Sequence[DocumentEmbeddingRecord], first_vector_id: int) -> list[tuple[Any, ...]]:
    return [
        (
            first_vector_id + offset,
            record.document_id,
            record.corpus,
            record.title,
            record.source_url,
            record.source_version,
            record.source_timestamp,
            record.lead_chunk_id,
            _json(list(record.heading_path)),
            record.lead_text,
        )
        for offset, record in enumerate(records)
    ]


def _validate_generation(index_path: Path, metadata_path: Path, expected: int, dimensions: int) -> None:
    index = faiss.read_index(str(index_path))
    if index.ntotal != expected or index.d != dimensions:
        raise RuntimeError(
            f"FAISS validation failed: expected {expected}x{dimensions}, found {index.ntotal}x{index.d}"
        )
    connection = sqlite3.connect(metadata_path)
    try:
        count = connection.execute("SELECT count(*) FROM vector_documents").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if count != expected:
            raise RuntimeError(f"Vector metadata count mismatch: expected {expected}, found {count}")
        if integrity != "ok":
            raise RuntimeError(f"Vector metadata integrity check failed: {integrity}")
        identifiers = connection.execute(
            "SELECT min(vector_id), max(vector_id), count(DISTINCT vector_id) FROM vector_documents"
        ).fetchone()
        if expected and identifiers != (0, expected - 1, expected):
            raise RuntimeError("Vector metadata IDs are not contiguous")
        has_content = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vector_content'"
        ).fetchone() is not None
        if has_content:
            content_count = int(connection.execute("SELECT count(*) FROM vector_content").fetchone()[0])
            orphaned = int(
                connection.execute(
                    "SELECT count(*) FROM vector_content vc "
                    "LEFT JOIN vector_documents vd ON vd.vector_id = vc.vector_id "
                    "WHERE vd.vector_id IS NULL"
                ).fetchone()[0]
            )
            if content_count != expected or orphaned:
                raise RuntimeError(
                    f"Vector content provenance mismatch: expected {expected}, found {content_count}, "
                    f"orphaned {orphaned}"
                )
    finally:
        connection.close()
    if expected:
        probe = np.empty((1, dimensions), dtype=np.float32)
        index.reconstruct(0, probe[0])
        scores, identifiers = index.search(probe, 1)
        if int(identifiers[0, 0]) != 0 or not np.isfinite(scores[0, 0]):
            raise RuntimeError("FAISS smoke search failed")


def build_vector_index(
    database: Path,
    directory: Path,
    provider: EmbeddingProvider,
    *,
    overwrite: bool = False,
    resume: bool = False,
    restart: bool = False,
    batch_size: int = 128,
    embedding_workers: int = 2,
    checkpoint_interval: int = 4_096,
    max_chunks: int = 2,
    max_characters: int = 8_000,
    reuse_from: Path | None = None,
    verify_reuse_checksums: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Build an atomic vector generation, optionally reusing unchanged prior vectors."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not 1 <= embedding_workers <= 8:
        raise ValueError("embedding_workers must be between 1 and 8")
    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    if resume and restart:
        raise ValueError("resume and restart are mutually exclusive")
    if provider.dimensions < 1:
        raise ValueError("provider dimensions must be positive")
    source_metadata = read_index_metadata(database)
    source_stat = database.stat()
    count_connection = _connect_read_only(database)
    try:
        source_document_count = int(
            source_metadata.get("document_count")
            or count_connection.execute("SELECT count(*) FROM documents").fetchone()[0]
        )
        expected_documents = int(count_connection.execute("SELECT count(DISTINCT document_id) FROM chunks").fetchone()[0])
    finally:
        count_connection.close()
    if source_document_count < 1:
        raise ValueError("Source index has no documents")
    if expected_documents < 1:
        raise ValueError("Source index has no searchable documents with chunks")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / MANIFEST_NAME
    previous = load_vector_manifest(directory) if manifest_path.exists() else None
    state = _load_build_state(directory)
    if state is not None and previous is not None and state.get("generation") == previous.get("generation"):
        # Publication succeeded and only checkpoint cleanup was interrupted.
        for key in ("raw_vectors_file", "metadata_file"):
            try:
                _safe_local_path(directory, state[key]).unlink()
            except FileNotFoundError:
                pass
        try:
            (directory / BUILD_STATE_NAME).unlink()
        except FileNotFoundError:
            pass
        return previous
    if state is not None and restart:
        _remove_build_checkpoint(directory, state)
        state = None
    elif state is not None and not resume:
        raise RuntimeError(
            f"An incomplete semantic build exists in {directory}; use resume=True or restart=True explicitly"
        )
    elif state is None and resume:
        raise FileNotFoundError(f"No semantic build checkpoint exists in {directory}")
    if previous is not None and state is None and not overwrite:
        raise FileExistsError(f"Vector index already exists: {directory}; authorize overwrite explicitly")

    source_identity = {
        "database": str(database.resolve()),
        "bytes": source_stat.st_size,
        "mtime_ns": source_stat.st_mtime_ns,
        "schema_version": source_metadata.get("schema_version", 1),
        "build_id": source_metadata.get("build_id"),
        "document_count": source_document_count,
        "searchable_document_count": expected_documents,
    }
    content_configuration = {"max_chunks": max_chunks, "max_characters": max_characters}
    reuse_source: _VectorReuseSource | None = None
    reuse_identity: dict[str, Any] | None = None
    if reuse_from is not None:
        reuse_source = _VectorReuseSource(
            reuse_from,
            provider,
            content_configuration,
            verify_checksums=verify_reuse_checksums,
        )
        reuse_identity = reuse_source.identity
    reuse_enabled = reuse_identity is not None
    if state is not None and state.get("reuse_identity") is not None and reuse_identity is None:
        raise ValueError("Semantic build checkpoint requires the original reuse generation")
    required_configuration = {
        "dimensions": provider.dimensions,
        "provider": dict(provider.provider_metadata),
        "source_identity": source_identity,
        "content_configuration": content_configuration,
        "embedding_execution": {"batch_size": batch_size, "workers": embedding_workers},
    }
    if reuse_identity is not None:
        required_configuration["reuse_identity"] = reuse_identity
    if state is None:
        generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        state = {
            "schema_version": BUILD_STATE_SCHEMA_VERSION,
            "status": "building",
            "generation": generation,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_documents": 0,
            "last_document_id": None,
            "raw_vector_bytes": 0,
            "raw_vectors_file": f".vectors-{generation}.f32.partial",
            "metadata_file": f".metadata-{generation}.sqlite3.partial",
            "final_faiss_file": f"vectors-{generation}.faiss",
            "final_metadata_file": f"metadata-{generation}.sqlite3",
            "replaces_generation": previous.get("generation") if previous is not None else None,
            "metadata_schema_version": VECTOR_METADATA_SCHEMA_VERSION,
            "documents_reused": 0,
            "documents_embedded": 0,
            **required_configuration,
        }
        try:
            _atomic_write_json(directory / BUILD_STATE_NAME, state)
        except BaseException:
            if reuse_source is not None:
                reuse_source.close()
            raise
    else:
        for key, expected in required_configuration.items():
            if state.get(key) != expected:
                if reuse_source is not None:
                    reuse_source.close()
                raise ValueError(f"Semantic build checkpoint mismatch for {key}")
        expected_replacement = previous.get("generation") if previous is not None else None
        if state.get("replaces_generation") != expected_replacement:
            if reuse_source is not None:
                reuse_source.close()
            raise ValueError("Semantic build checkpoint replacement target changed")

    generation = str(state["generation"])
    raw_vectors = _safe_local_path(directory, state["raw_vectors_file"])
    temporary_metadata = _safe_local_path(directory, state["metadata_file"])
    final_faiss = _safe_local_path(directory, state["final_faiss_file"])
    final_metadata = _safe_local_path(directory, state["final_metadata_file"])
    temporary_faiss = directory / f".{final_faiss.name}.building"
    started = time.monotonic()
    connection: sqlite3.Connection | None = None
    raw_stream: Any | None = None
    count = 0
    last_document_id: str | None = None
    last_checkpoint_count = 0
    published_files = False
    manifest_published = False
    try:
        connection, raw_stream, count, last_document_id, state = _reconcile_build_checkpoint(directory, state)
        metadata_schema_version = int(state.get("metadata_schema_version", 1))
        if metadata_schema_version >= 2:
            connection.executescript(VECTOR_CONTENT_SCHEMA)
            connection.execute("DELETE FROM vector_content WHERE vector_id >= ?", (count,))
            connection.commit()
            reused_count = int(
                connection.execute(
                    "SELECT count(*) FROM vector_content WHERE reused_from_vector_id IS NOT NULL"
                ).fetchone()[0]
            )
            embedded_count = count - reused_count
        else:
            reused_count = 0
            embedded_count = count
        last_checkpoint_count = count
        records = iter_document_embedding_records(
            database,
            max_chunks=max_chunks,
            max_characters=max_characters,
            start_after_document_id=last_document_id,
        )
        insert_sql = "INSERT INTO vector_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        if reuse_source is not None:
            batches: Iterable[tuple[list[DocumentEmbeddingRecord], np.ndarray, list[int | None]]] = (
                _reuse_aware_batches(
                    records,
                    provider,
                    reuse_source,
                    batch_size=batch_size,
                    workers=embedding_workers,
                )
            )
        else:
            batches = (
                (batch, vectors, [None] * len(batch))
                for batch, vectors in _embedded_batches(
                    records,
                    provider,
                    batch_size=batch_size,
                    workers=embedding_workers,
                )
            )
        for batch, vectors, reused_from in batches:
            if vectors.shape != (len(batch), provider.dimensions):
                raise RuntimeError(f"Embedding provider returned an unexpected shape: {vectors.shape}")
            vectors = np.ascontiguousarray(vectors, dtype=np.float32)
            raw_stream.write(vectors.tobytes(order="C"))
            connection.executemany(insert_sql, _metadata_rows(batch, count))
            if metadata_schema_version >= 2:
                connection.executemany(
                    "INSERT INTO vector_content(vector_id, embedding_text_sha256, "
                    "reused_from_generation, reused_from_vector_id) VALUES (?, ?, ?, ?)",
                    (
                        (
                            count + offset,
                            embedding_text_sha256(record.embedding_text),
                            reuse_source.generation if prior_vector_id is not None and reuse_source is not None else None,
                            prior_vector_id,
                        )
                        for offset, (record, prior_vector_id) in enumerate(zip(batch, reused_from, strict=True))
                    ),
                )
            batch_reused = sum(value is not None for value in reused_from)
            reused_count += batch_reused
            embedded_count += len(batch) - batch_reused
            count += len(batch)
            last_document_id = batch[-1].document_id
            if count - last_checkpoint_count >= checkpoint_interval:
                state = {
                    **state,
                    "documents_reused": reused_count,
                    "documents_embedded": embedded_count,
                }
                state = _checkpoint_build(
                    directory,
                    state,
                    raw_stream,
                    connection,
                    count,
                    last_document_id,
                )
                last_checkpoint_count = count
                if progress is not None:
                    progress(count, expected_documents)
        state = {
            **state,
            "documents_reused": reused_count,
            "documents_embedded": embedded_count,
        }
        state = _checkpoint_build(
            directory,
            state,
            raw_stream,
            connection,
            count,
            last_document_id,
        )
        if progress is not None and count != last_checkpoint_count:
            progress(count, expected_documents)
        if count != expected_documents:
            raise RuntimeError(f"Source document count changed: expected {expected_documents}, indexed {count}")
        final_source_stat = database.stat()
        if (final_source_stat.st_size, final_source_stat.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise RuntimeError("Source database changed during semantic index construction")
        build_metadata = {
            "schema_version": VECTOR_SCHEMA_VERSION,
            "metadata_schema_version": metadata_schema_version,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "document_count": count,
            "source_document_count": source_document_count,
            "dimensions": provider.dimensions,
            "provider": state["provider"],
            "embedding_execution": state["embedding_execution"],
            "source_database": source_identity["database"],
            "source_database_bytes": source_identity["bytes"],
            "source_database_mtime_ns": source_identity["mtime_ns"],
            "source_schema_version": source_identity["schema_version"],
            "source_build_id": source_identity["build_id"],
            "content_configuration": state["content_configuration"],
            "index_configuration": {"type": "IndexFlatIP", "metric": "cosine_on_l2_normalized_vectors"},
            "checkpoint_configuration": {
                "format": "float32-row-major",
                "interval_documents": checkpoint_interval,
                "resume_supported": True,
            },
            "reuse": {
                "enabled": reuse_enabled,
                "base": reuse_identity,
                "documents_reused": reused_count,
                "documents_embedded": embedded_count,
                "reuse_rate": round(reused_count / count, 8) if count else 0.0,
            },
        }
        connection.execute("DELETE FROM vector_metadata")
        connection.executemany(
            "INSERT INTO vector_metadata(key, value_json) VALUES (?, ?)",
            ((key, _json(value)) for key, value in sorted(build_metadata.items())),
        )
        connection.commit()
        connection.close()
        connection = None
        raw_stream.close()
        raw_stream = None
        if reuse_source is not None:
            reuse_source.assert_unchanged()
            reuse_source.close()
            reuse_source = None

        index = faiss.IndexFlatIP(provider.dimensions)
        matrix = np.memmap(raw_vectors, dtype=np.float32, mode="r", shape=(count, provider.dimensions))
        try:
            for offset in range(0, count, 100_000):
                index.add(np.ascontiguousarray(matrix[offset : offset + 100_000]))
        finally:
            del matrix
        faiss.write_index(index, str(temporary_faiss))
        _validate_generation(temporary_faiss, temporary_metadata, count, provider.dimensions)
        os.replace(temporary_faiss, final_faiss)
        os.replace(temporary_metadata, final_metadata)
        published_files = True
        manifest = {
            **build_metadata,
            "generation": generation,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "files": {
                "faiss": {
                    "name": final_faiss.name,
                    "bytes": final_faiss.stat().st_size,
                    "sha256": _sha256(final_faiss),
                },
                "metadata": {
                    "name": final_metadata.name,
                    "bytes": final_metadata.stat().st_size,
                    "sha256": _sha256(final_metadata),
                },
            },
        }
        _atomic_write_json(manifest_path, manifest)
        manifest_published = True
    except BaseException:
        if connection is not None and raw_stream is not None:
            try:
                state = _checkpoint_build(
                    directory,
                    state,
                    raw_stream,
                    connection,
                    count,
                    last_document_id,
                )
            except BaseException:
                pass
        if raw_stream is not None:
            raw_stream.close()
        if connection is not None:
            connection.close()
        if reuse_source is not None:
            reuse_source.close()
        try:
            temporary_faiss.unlink()
        except FileNotFoundError:
            pass
        if final_metadata.exists() and not manifest_published:
            try:
                os.replace(final_metadata, temporary_metadata)
            except OSError:
                pass
        if published_files and not manifest_published:
            try:
                final_faiss.unlink()
            except FileNotFoundError:
                pass
        raise

    try:
        raw_vectors.unlink()
    except FileNotFoundError:
        pass
    try:
        (directory / BUILD_STATE_NAME).unlink()
    except FileNotFoundError:
        pass
    if previous is not None:
        for file_value in previous["files"].values():
            old_path = directory / str(file_value["name"])
            if old_path not in {final_faiss, final_metadata}:
                try:
                    old_path.unlink()
                except OSError:
                    pass
    return load_vector_manifest(directory)


class VectorIndex:
    """Read-only document-level FAISS index with SQLite citation metadata."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.manifest = load_vector_manifest(self.directory)
        self.index = faiss.read_index(str(self.directory / self.manifest["files"]["faiss"]["name"]))
        self.connection = _connect_read_only(self.directory / self.manifest["files"]["metadata"]["name"])
        self._search_lock = threading.Lock()
        if self.index.ntotal != int(self.manifest["document_count"]):
            self.close()
            raise RuntimeError("Loaded FAISS count does not match its manifest")

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None  # type: ignore[assignment]

    def __enter__(self) -> VectorIndex:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query_vector: np.ndarray, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.shape != (self.index.d,):
            raise ValueError(f"Expected query vector shape {(self.index.d,)}, got {vector.shape}")
        vector = np.ascontiguousarray(vector.reshape(1, -1), dtype=np.float32)
        with self._search_lock:
            scores, identifiers = self.index.search(vector, min(limit, self.index.ntotal))
            ordered_ids = [int(value) for value in identifiers[0] if int(value) >= 0]
            if not ordered_ids:
                return []
            placeholders = ",".join("?" for _ in ordered_ids)
            rows = self.connection.execute(
                f"SELECT * FROM vector_documents WHERE vector_id IN ({placeholders})",
                ordered_ids,
            ).fetchall()
        by_id = {int(row["vector_id"]): dict(row) for row in rows}
        results: list[dict[str, Any]] = []
        for rank, (vector_id, score) in enumerate(zip(ordered_ids, scores[0], strict=True), start=1):
            item = by_id[vector_id]
            item["heading_path"] = json.loads(item.pop("heading_path_json"))
            item["text"] = item.pop("lead_text")
            item["chunk_id"] = item.pop("lead_chunk_id")
            item["raw_score"] = float(score)
            item["score"] = float(score)
            item["semantic_rank"] = rank
            item["ranking_reason"] = "semantic"
            item["citation"] = _citation(item)
            results.append(item)
        return results


def semantic_search(
    vector_index: VectorIndex,
    provider: EmbeddingProvider,
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if provider.dimensions != vector_index.index.d:
        raise ValueError(
            f"Embedding dimensions {provider.dimensions} do not match vector index dimensions {vector_index.index.d}"
        )
    return vector_index.search(provider.embed_query(query), limit)


def hybrid_search(
    database: Path,
    vector_index: VectorIndex,
    provider: EmbeddingProvider,
    query: str,
    *,
    limit: int = 20,
    mode: str = "and",
    lexical_candidates: int = 100,
    semantic_candidates: int = 100,
    rrf_k: float = 60.0,
    lexical_weight: float = 1.0,
    semantic_weight: float = 1.0,
) -> dict[str, Any]:
    """Fuse distinct BM25 and semantic document rankings with weighted RRF."""

    if limit < 1:
        raise ValueError("limit must be positive")
    if lexical_candidates < limit or semantic_candidates < limit:
        raise ValueError("candidate counts must be at least limit")
    if rrf_k <= 0 or lexical_weight <= 0 or semantic_weight <= 0:
        raise ValueError("RRF k and weights must be positive")
    lexical = search_documents(
        database,
        query,
        limit=min(50, lexical_candidates),
        mode=mode,
        candidate_limit=lexical_candidates,
    )["results"]
    semantic = semantic_search(vector_index, provider, query, limit=semantic_candidates)
    scores: dict[str, float] = {}
    representatives: dict[str, dict[str, Any]] = {}
    contributions: dict[str, dict[str, float | int | None]] = {}
    for source, weight, candidates in (
        ("lexical", lexical_weight, lexical),
        ("semantic", semantic_weight, semantic),
    ):
        for rank, candidate in enumerate(candidates, start=1):
            document_id = str(candidate["document_id"])
            contribution = weight / (rrf_k + rank)
            scores[document_id] = scores.get(document_id, 0.0) + contribution
            values = contributions.setdefault(
                document_id,
                {"lexical_rank": None, "semantic_rank": None, "lexical_rrf": 0.0, "semantic_rrf": 0.0},
            )
            values[f"{source}_rank"] = rank
            values[f"{source}_rrf"] = contribution
            if document_id not in representatives or source == "lexical":
                representatives[document_id] = dict(candidate)
    ordered = sorted(scores, key=lambda document_id: (-scores[document_id], document_id))[:limit]
    results: list[dict[str, Any]] = []
    for document_id in ordered:
        item = representatives[document_id]
        item["raw_score"] = scores[document_id]
        item["score"] = scores[document_id]
        item["fusion_score"] = scores[document_id]
        item["fusion"] = contributions[document_id]
        item["ranking_reason"] = "hybrid_rrf"
        results.append(item)
    return {
        "query": query,
        "mode": mode,
        "ranking_unit": "document",
        "retriever": "hybrid_rrf",
        "lexical_candidates": len(lexical),
        "semantic_candidates": len(semantic),
        "rrf_k": rrf_k,
        "weights": {"lexical": lexical_weight, "semantic": semantic_weight},
        "results": results,
    }


def _progress(count: int, total: int) -> None:
    print(_json({"indexed": count, "total": total, "percent": round(count / total * 100, 2)}), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query a local document-level semantic index.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--models", type=Path, default=Path("config/models.json"))
    build.add_argument("--model-id")
    build.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    build.add_argument("--batch-size", type=int, default=128)
    build.add_argument("--embedding-workers", type=int, default=2)
    build.add_argument("--checkpoint-interval", type=int, default=4_096)
    build.add_argument("--max-chunks", type=int, default=2)
    build.add_argument("--max-characters", type=int, default=8_000)
    build.add_argument(
        "--reuse-from",
        type=Path,
        help="Compatible published vector generation used to reuse unchanged document vectors",
    )
    build.add_argument(
        "--skip-reuse-checksums",
        action="store_true",
        help="Trust recorded reuse-generation file sizes instead of rehashing its files",
    )
    build.add_argument("--overwrite", action="store_true")
    build.add_argument("--resume", action="store_true")
    build.add_argument("--restart", action="store_true")
    query = subparsers.add_parser("query")
    query.add_argument("--database", type=Path, required=True)
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--models", type=Path, default=Path("config/models.json"))
    query.add_argument("--model-id")
    query.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--mode", choices=("semantic", "hybrid"), default="hybrid")
    evaluation = subparsers.add_parser("evaluate")
    evaluation.add_argument("--database", type=Path, required=True)
    evaluation.add_argument("--index", type=Path, required=True)
    evaluation.add_argument("--suite", type=Path, required=True)
    evaluation.add_argument("--output", type=Path)
    evaluation.add_argument("--models", type=Path, default=Path("config/models.json"))
    evaluation.add_argument("--model-id")
    evaluation.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    evaluation.add_argument("--mode", choices=("semantic", "hybrid", "all"), default="all")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--index", type=Path, required=True)
    verify.add_argument("--database", type=Path)
    verify.add_argument("--skip-checksums", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        result = verify_vector_index(
            args.index,
            database=args.database,
            verify_checksums=not args.skip_checksums,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    config = load_embedding_model_config(args.models, args.model_id)
    provider = OllamaEmbeddingClient(config, base_url=args.ollama_url)
    if args.command == "build":
        result = build_vector_index(
            args.database,
            args.output,
            provider,
            overwrite=args.overwrite,
            resume=args.resume,
            restart=args.restart,
            batch_size=args.batch_size,
            embedding_workers=args.embedding_workers,
            checkpoint_interval=args.checkpoint_interval,
            max_chunks=args.max_chunks,
            max_characters=args.max_characters,
            reuse_from=args.reuse_from,
            verify_reuse_checksums=not args.skip_reuse_checksums,
            progress=_progress,
        )
    elif args.command == "query":
        with VectorIndex(args.index) as index:
            if args.mode == "semantic":
                result = semantic_search(index, provider, args.query, limit=args.limit)
            else:
                result = hybrid_search(args.database, index, provider, args.query, limit=args.limit)
    else:
        with VectorIndex(args.index) as index:
            identity = {
                "database": str(args.database.resolve()),
                "vector_directory": str(args.index.resolve()),
                "vector_manifest": index.manifest,
            }
            result = {}
            if args.mode == "all":
                result["bm25"] = evaluate(args.database, args.suite)
            if args.mode in {"semantic", "all"}:
                result["semantic"] = evaluate_retriever(
                    args.suite,
                    lambda query, limit, _mode: semantic_search(index, provider, query, limit=limit),
                    retrieval_identity={"retriever": "faiss_semantic", **identity},
                )
            if args.mode in {"hybrid", "all"}:
                result["hybrid"] = evaluate_retriever(
                    args.suite,
                    lambda query, limit, mode: hybrid_search(
                        args.database,
                        index,
                        provider,
                        query,
                        limit=limit,
                        mode=mode,
                        lexical_candidates=max(100, limit),
                        semantic_candidates=max(100, limit),
                    )["results"],
                    retrieval_identity={"retriever": "weighted_rrf", **identity},
                )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
