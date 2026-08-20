from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
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
from .vector_index import (
    MANIFEST_NAME,
    _atomic_write_json,
    _json,
    _safe_local_path,
    _sha256,
    embedding_text_sha256,
    hybrid_search,
    load_vector_manifest,
)


CHUNK_REPRESENTATION = "title-heading-chunk-v1"
CHUNK_BUILD_STATE_SCHEMA_VERSION = 1
CHUNK_METADATA_SCHEMA_VERSION = 1
BUILD_STATE_NAME = ".chunk-build-state.json"


METADATA_SCHEMA = """
CREATE TABLE vector_chunks (
    vector_id INTEGER PRIMARY KEY,
    chunk_instance_id TEXT NOT NULL UNIQUE,
    content_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    embedding_text_sha256 TEXT NOT NULL,
    reused_from_generation TEXT,
    reused_from_vector_id INTEGER
);
CREATE INDEX vector_chunks_document_id_idx ON vector_chunks(document_id);
CREATE INDEX vector_chunks_content_id_idx ON vector_chunks(content_id);
CREATE INDEX vector_chunks_embedding_sha256_idx ON vector_chunks(embedding_text_sha256);
CREATE TABLE vector_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ChunkEmbeddingRecord:
    chunk_instance_id: str
    content_id: str
    document_id: str
    corpus: str
    title: str
    source_url: str | None
    source_version: str | None
    source_timestamp: str | None
    ordinal: int
    heading_path: tuple[str, ...]
    text: str
    embedding_text: str


def _connect_read_only(path: Path, *, thread_safe: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
        check_same_thread=not thread_safe,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _heading_parts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(">") if part.strip())


def chunk_embedding_text(title: str, heading_path: Sequence[str], text: str, max_characters: int) -> str:
    """Create the stable title/section/body representation supplied to the model."""

    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    heading = " > ".join(part.strip() for part in heading_path if part.strip())
    prefix = f"Title: {title.strip()}"
    if heading:
        prefix += f"\nSection: {heading}"
    body = text.strip()
    available = max(1, max_characters - len(prefix) - 2)
    return f"{prefix}\n\n{body[:available]}"


def iter_chunk_embedding_records(
    database: Path,
    *,
    max_characters: int = 4_000,
    start_after_chunk_id: str | None = None,
) -> Iterator[ChunkEmbeddingRecord]:
    """Stream all common-schema chunks in stable chunk-instance-ID order."""

    metadata = read_index_metadata(database)
    if int(metadata.get("schema_version", 1)) < 2:
        raise ValueError("Chunk-level semantic indexing requires a schema-version-2 BM25 database")
    connection = _connect_read_only(database)
    try:
        rows = connection.execute(
            """
            SELECT c.chunk_instance_id, c.content_id, c.document_id, d.corpus, d.title,
                   d.source_url, d.source_version, d.source_timestamp, c.ordinal,
                   c.heading_path, c.text
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            WHERE c.chunk_instance_id > ?
            ORDER BY c.chunk_instance_id
            """,
            (start_after_chunk_id or "",),
        )
        for row in rows:
            headings = _heading_parts(str(row["heading_path"]))
            text = str(row["text"])
            title = str(row["title"])
            yield ChunkEmbeddingRecord(
                chunk_instance_id=str(row["chunk_instance_id"]),
                content_id=str(row["content_id"]),
                document_id=str(row["document_id"]),
                corpus=str(row["corpus"]),
                title=title,
                source_url=row["source_url"],
                source_version=row["source_version"],
                source_timestamp=row["source_timestamp"],
                ordinal=int(row["ordinal"]),
                heading_path=headings,
                text=text,
                embedding_text=chunk_embedding_text(title, headings, text, max_characters),
            )
    finally:
        connection.close()


def _batched(values: Iterable[ChunkEmbeddingRecord], size: int) -> Iterator[list[ChunkEmbeddingRecord]]:
    if size < 1:
        raise ValueError("batch_size must be positive")
    batch: list[ChunkEmbeddingRecord] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _embedded_batches(
    values: Iterable[ChunkEmbeddingRecord],
    provider: EmbeddingProvider,
    *,
    batch_size: int,
    workers: int,
) -> Iterator[tuple[list[ChunkEmbeddingRecord], np.ndarray]]:
    """Embed bounded batches concurrently while preserving deterministic order."""

    if workers < 1:
        raise ValueError("embedding_workers must be positive")
    batches = _batched(values, batch_size)
    if workers == 1:
        for batch in batches:
            yield batch, provider.embed_documents([record.embedding_text for record in batch])
        return
    pending: deque[tuple[list[ChunkEmbeddingRecord], Future[np.ndarray]]] = deque()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chunk-embedding") as executor:
        for batch in batches:
            pending.append(
                (batch, executor.submit(provider.embed_documents, [record.embedding_text for record in batch]))
            )
            if len(pending) >= workers:
                first_batch, first_future = pending.popleft()
                yield first_batch, first_future.result()
        while pending:
            batch, future = pending.popleft()
            yield batch, future.result()


def load_chunk_vector_manifest(directory: Path) -> dict[str, Any]:
    manifest = load_vector_manifest(directory)
    if manifest.get("representation") != CHUNK_REPRESENTATION:
        raise ValueError(f"Vector generation is not a chunk-level index: {directory}")
    if int(manifest.get("chunk_count", -1)) < 1:
        raise ValueError(f"Chunk vector manifest has an invalid chunk count: {directory}")
    return manifest


class _ChunkReuseSource:
    def __init__(
        self,
        directory: Path,
        provider: EmbeddingProvider,
        representation_configuration: Mapping[str, Any],
        *,
        verify_checksums: bool,
    ) -> None:
        self.directory = directory.resolve()
        self.manifest = load_chunk_vector_manifest(self.directory)
        if int(self.manifest["dimensions"]) != provider.dimensions:
            raise ValueError("Reuse generation dimensions do not match the selected provider")
        if self.manifest.get("provider") != dict(provider.provider_metadata):
            raise ValueError("Reuse generation provider does not match the selected provider")
        if self.manifest.get("representation_configuration") != dict(representation_configuration):
            raise ValueError("Reuse generation representation does not match")
        if verify_checksums:
            verify_chunk_vector_index(self.directory)
        self.generation = str(self.manifest["generation"])
        self.manifest_path = self.directory / MANIFEST_NAME
        self.faiss_path = self.directory / str(self.manifest["files"]["faiss"]["name"])
        self.metadata_path = self.directory / str(self.manifest["files"]["metadata"]["name"])
        self.initial_stats = self._file_stats()
        self.index = faiss.read_index(str(self.faiss_path))
        self.connection = _connect_read_only(self.metadata_path)

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "generation": self.generation,
            "manifest_sha256": _sha256(self.manifest_path),
            "faiss_sha256": self.manifest["files"]["faiss"]["sha256"],
            "metadata_sha256": self.manifest["files"]["metadata"]["sha256"],
            "file_stats": self.initial_stats,
        }

    def _file_stats(self) -> dict[str, list[int]]:
        return {
            path.name: [path.stat().st_size, path.stat().st_mtime_ns]
            for path in (self.manifest_path, self.faiss_path, self.metadata_path)
        }

    def assert_unchanged(self) -> None:
        if self._file_stats() != self.initial_stats:
            raise RuntimeError("Reuse generation changed during chunk semantic construction")

    def resolve(
        self,
        records: Sequence[ChunkEmbeddingRecord],
        dimensions: int,
    ) -> tuple[np.ndarray, list[int], list[int | None]]:
        fingerprints = [embedding_text_sha256(record.embedding_text) for record in records]
        placeholders = ",".join("?" for _ in fingerprints)
        rows = self.connection.execute(
            f"""
            SELECT min(vector_id) AS vector_id, embedding_text_sha256
            FROM vector_chunks
            WHERE embedding_text_sha256 IN ({placeholders})
            GROUP BY embedding_text_sha256
            """,
            fingerprints,
        ).fetchall()
        prior = {str(row["embedding_text_sha256"]): int(row["vector_id"]) for row in rows}
        vectors = np.empty((len(records), dimensions), dtype=np.float32)
        missing: list[int] = []
        reused_from: list[int | None] = [None] * len(records)
        positions: list[int] = []
        identifiers: list[int] = []
        for position, fingerprint in enumerate(fingerprints):
            vector_id = prior.get(fingerprint)
            if vector_id is None:
                missing.append(position)
            else:
                positions.append(position)
                identifiers.append(vector_id)
                reused_from[position] = vector_id
        if identifiers:
            restored = self.index.reconstruct_batch(np.asarray(identifiers, dtype=np.int64))
            vectors[np.asarray(positions, dtype=np.int64)] = np.asarray(restored, dtype=np.float32)
        return vectors, missing, reused_from

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None  # type: ignore[assignment]
        self.index = None  # type: ignore[assignment]


def _reuse_aware_batches(
    values: Iterable[ChunkEmbeddingRecord],
    provider: EmbeddingProvider,
    reuse: _ChunkReuseSource,
    *,
    batch_size: int,
    workers: int,
) -> Iterator[tuple[list[ChunkEmbeddingRecord], np.ndarray, list[int | None]]]:
    pending: deque[
        tuple[list[ChunkEmbeddingRecord], np.ndarray, list[int], list[int | None], Future[np.ndarray] | None]
    ] = deque()

    def finish(
        item: tuple[
            list[ChunkEmbeddingRecord], np.ndarray, list[int], list[int | None], Future[np.ndarray] | None
        ],
    ) -> tuple[list[ChunkEmbeddingRecord], np.ndarray, list[int | None]]:
        batch, vectors, missing, reused_from, future = item
        if future is not None:
            embedded = future.result()
            if embedded.shape != (len(missing), provider.dimensions):
                raise RuntimeError(f"Embedding provider returned an unexpected shape: {embedded.shape}")
            vectors[np.asarray(missing, dtype=np.int64)] = embedded
        return batch, np.ascontiguousarray(vectors, dtype=np.float32), reused_from

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chunk-embedding") as executor:
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


def _load_state(directory: Path) -> dict[str, Any] | None:
    path = directory / BUILD_STATE_NAME
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != CHUNK_BUILD_STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported chunk semantic checkpoint: {path}")
    for key in ("raw_vectors_file", "metadata_file", "final_faiss_file", "final_metadata_file"):
        _safe_local_path(directory, value.get(key))
    return value


def _remove_checkpoint(directory: Path, state: Mapping[str, Any]) -> None:
    for key in ("raw_vectors_file", "metadata_file", "final_faiss_file", "final_metadata_file"):
        try:
            _safe_local_path(directory, state.get(key)).unlink()
        except FileNotFoundError:
            pass
    try:
        (directory / BUILD_STATE_NAME).unlink()
    except FileNotFoundError:
        pass


def _checkpoint(
    directory: Path,
    state: Mapping[str, Any],
    raw_stream: Any,
    connection: sqlite3.Connection,
    count: int,
    last_chunk_id: str | None,
) -> dict[str, Any]:
    raw_stream.flush()
    os.fsync(raw_stream.fileno())
    connection.commit()
    updated = {
        **state,
        "checkpointed_at": datetime.now(timezone.utc).isoformat(),
        "completed_chunks": count,
        "last_chunk_instance_id": last_chunk_id,
        "raw_vector_bytes": count * int(state["dimensions"]) * np.dtype(np.float32).itemsize,
    }
    _atomic_write_json(directory / BUILD_STATE_NAME, updated)
    return updated


def _reconcile(
    directory: Path,
    state: Mapping[str, Any],
) -> tuple[sqlite3.Connection, Any, int, str | None, dict[str, Any]]:
    raw_path = _safe_local_path(directory, state["raw_vectors_file"])
    metadata_path = _safe_local_path(directory, state["metadata_file"])
    final_metadata = _safe_local_path(directory, state["final_metadata_file"])
    if not metadata_path.exists() and final_metadata.exists():
        os.replace(final_metadata, metadata_path)
    if not metadata_path.exists() and int(state.get("completed_chunks", 0)) == 0:
        connection = sqlite3.connect(metadata_path)
        connection.executescript(METADATA_SCHEMA)
        connection.commit()
        connection.close()
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Chunk semantic checkpoint metadata is missing: {metadata_path}")
    if not raw_path.exists():
        raw_path.touch()
    connection = sqlite3.connect(metadata_path)
    raw_stream = raw_path.open("r+b")
    try:
        bytes_per_vector = int(state["dimensions"]) * np.dtype(np.float32).itemsize
        raw_count = raw_path.stat().st_size // bytes_per_vector
        metadata_count = int(connection.execute("SELECT count(*) FROM vector_chunks").fetchone()[0])
        consistent = min(raw_count, metadata_count)
        connection.execute("DELETE FROM vector_chunks WHERE vector_id >= ?", (consistent,))
        connection.commit()
        raw_stream.truncate(consistent * bytes_per_vector)
        raw_stream.seek(0, os.SEEK_END)
        row = connection.execute(
            "SELECT chunk_instance_id FROM vector_chunks WHERE vector_id = ?", (consistent - 1,)
        ).fetchone()
        last_chunk_id = str(row[0]) if row is not None else None
        updated = _checkpoint(directory, state, raw_stream, connection, consistent, last_chunk_id)
        return connection, raw_stream, consistent, last_chunk_id, updated
    except BaseException:
        raw_stream.close()
        connection.close()
        raise


def _validate_generation(index_path: Path, metadata_path: Path, expected: int, dimensions: int) -> None:
    index = faiss.read_index(str(index_path))
    if index.ntotal != expected or index.d != dimensions:
        raise RuntimeError(f"FAISS validation failed: expected {expected}x{dimensions}, found {index.ntotal}x{index.d}")
    connection = sqlite3.connect(metadata_path)
    try:
        count = int(connection.execute("SELECT count(*) FROM vector_chunks").fetchone()[0])
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        identifiers = connection.execute(
            "SELECT min(vector_id), max(vector_id), count(DISTINCT vector_id) FROM vector_chunks"
        ).fetchone()
        if count != expected:
            raise RuntimeError(f"Chunk metadata count mismatch: expected {expected}, found {count}")
        if integrity != "ok":
            raise RuntimeError(f"Chunk metadata integrity check failed: {integrity}")
        if expected and identifiers != (0, expected - 1, expected):
            raise RuntimeError("Chunk vector IDs are not contiguous")
    finally:
        connection.close()
    if expected:
        probe = np.empty((1, dimensions), dtype=np.float32)
        index.reconstruct(0, probe[0])
        scores, identifiers = index.search(probe, 1)
        if int(identifiers[0, 0]) != 0 or not np.isfinite(scores[0, 0]):
            raise RuntimeError("Chunk FAISS smoke search failed")


def verify_chunk_vector_index(
    directory: Path,
    *,
    database: Path | None = None,
    verify_checksums: bool = True,
) -> dict[str, Any]:
    manifest = load_chunk_vector_manifest(directory)
    files = manifest["files"]
    if verify_checksums:
        for key in ("faiss", "metadata"):
            path = directory / str(files[key]["name"])
            if _sha256(path) != files[key].get("sha256"):
                raise ValueError(f"Chunk vector generation checksum mismatch: {path}")
    count = int(manifest["chunk_count"])
    dimensions = int(manifest["dimensions"])
    _validate_generation(
        directory / str(files["faiss"]["name"]),
        directory / str(files["metadata"]["name"]),
        count,
        dimensions,
    )
    source_verified = False
    if database is not None:
        stat = database.stat()
        if str(database.resolve()) != str(manifest.get("source_database")):
            raise ValueError("Chunk vector source database path mismatch")
        if stat.st_size != int(manifest.get("source_database_bytes", -1)):
            raise ValueError("Chunk vector source database size mismatch")
        metadata = read_index_metadata(database)
        if metadata.get("build_id") != manifest.get("source_build_id"):
            raise ValueError("Chunk vector source build ID mismatch")
        connection = _connect_read_only(database)
        try:
            source_chunks = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        finally:
            connection.close()
        if source_chunks != count:
            raise ValueError(f"Source chunk count mismatch: expected {count}, found {source_chunks}")
        source_verified = True
    return {
        "verified": True,
        "directory": str(directory.resolve()),
        "generation": manifest["generation"],
        "chunks": count,
        "dimensions": dimensions,
        "checksums_verified": verify_checksums,
        "source_verified": source_verified,
    }


def build_chunk_vector_index(
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
    max_characters: int = 4_000,
    reuse_from: Path | None = None,
    verify_reuse_checksums: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Build an atomic, resumable vector for every source chunk."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not 1 <= embedding_workers <= 8:
        raise ValueError("embedding_workers must be between 1 and 8")
    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    if max_characters < 256:
        raise ValueError("max_characters must be at least 256")
    if resume and restart:
        raise ValueError("resume and restart are mutually exclusive")
    source_metadata = read_index_metadata(database)
    if int(source_metadata.get("schema_version", 1)) < 2:
        raise ValueError("Chunk-level semantic indexing requires a schema-version-2 BM25 database")
    source_stat = database.stat()
    source_connection = _connect_read_only(database)
    try:
        source_documents = int(source_connection.execute("SELECT count(*) FROM documents").fetchone()[0])
        expected_chunks = int(source_connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
    finally:
        source_connection.close()
    if source_documents < 1 or expected_chunks < 1:
        raise ValueError("Source index has no searchable content")

    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / MANIFEST_NAME
    previous = load_chunk_vector_manifest(directory) if manifest_path.exists() else None
    state = _load_state(directory)
    if state is not None and previous is not None and state.get("generation") == previous.get("generation"):
        _remove_checkpoint(directory, state)
        return previous
    if state is not None and restart:
        _remove_checkpoint(directory, state)
        state = None
    elif state is not None and not resume:
        raise RuntimeError(f"An incomplete chunk semantic build exists in {directory}; use resume or restart")
    elif state is None and resume:
        raise FileNotFoundError(f"No chunk semantic checkpoint exists in {directory}")
    if previous is not None and state is None and not overwrite:
        raise FileExistsError(f"Chunk vector index already exists: {directory}; authorize overwrite explicitly")

    source_identity = {
        "database": str(database.resolve()),
        "bytes": source_stat.st_size,
        "mtime_ns": source_stat.st_mtime_ns,
        "schema_version": source_metadata.get("schema_version"),
        "build_id": source_metadata.get("build_id"),
        "document_count": source_documents,
        "chunk_count": expected_chunks,
    }
    representation_configuration = {
        "name": CHUNK_REPRESENTATION,
        "max_characters": max_characters,
        "prefix_fields": ["title", "heading_path"],
    }
    reuse: _ChunkReuseSource | None = None
    reuse_identity: dict[str, Any] | None = None
    if reuse_from is not None:
        reuse = _ChunkReuseSource(
            reuse_from,
            provider,
            representation_configuration,
            verify_checksums=verify_reuse_checksums,
        )
        reuse_identity = reuse.identity
    required = {
        "dimensions": provider.dimensions,
        "provider": dict(provider.provider_metadata),
        "source_identity": source_identity,
        "representation_configuration": representation_configuration,
        "embedding_execution": {"batch_size": batch_size, "workers": embedding_workers},
        "reuse_identity": reuse_identity,
    }
    if state is None:
        generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        state = {
            "schema_version": CHUNK_BUILD_STATE_SCHEMA_VERSION,
            "status": "building",
            "generation": generation,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_chunks": 0,
            "last_chunk_instance_id": None,
            "raw_vector_bytes": 0,
            "raw_vectors_file": f".chunk-vectors-{generation}.f32.partial",
            "metadata_file": f".chunk-metadata-{generation}.sqlite3.partial",
            "final_faiss_file": f"chunk-vectors-{generation}.faiss",
            "final_metadata_file": f"chunk-metadata-{generation}.sqlite3",
            "replaces_generation": previous.get("generation") if previous else None,
            "metadata_schema_version": CHUNK_METADATA_SCHEMA_VERSION,
            "chunks_reused": 0,
            "chunks_embedded": 0,
            **required,
        }
        _atomic_write_json(directory / BUILD_STATE_NAME, state)
    else:
        for key, expected in required.items():
            if state.get(key) != expected:
                if reuse is not None:
                    reuse.close()
                raise ValueError(f"Chunk semantic checkpoint mismatch for {key}")
        expected_replacement = previous.get("generation") if previous else None
        if state.get("replaces_generation") != expected_replacement:
            if reuse is not None:
                reuse.close()
            raise ValueError("Chunk semantic checkpoint replacement target changed")

    generation = str(state["generation"])
    raw_vectors = _safe_local_path(directory, state["raw_vectors_file"])
    temporary_metadata = _safe_local_path(directory, state["metadata_file"])
    final_faiss = _safe_local_path(directory, state["final_faiss_file"])
    final_metadata = _safe_local_path(directory, state["final_metadata_file"])
    temporary_faiss = directory / f".{final_faiss.name}.building"
    connection: sqlite3.Connection | None = None
    raw_stream: Any | None = None
    count = 0
    last_chunk_id: str | None = None
    manifest_published = False
    published_files = False
    started = time.monotonic()
    try:
        connection, raw_stream, count, last_chunk_id, state = _reconcile(directory, state)
        reused_count = int(
            connection.execute(
                "SELECT count(*) FROM vector_chunks WHERE reused_from_vector_id IS NOT NULL"
            ).fetchone()[0]
        )
        embedded_count = count - reused_count
        last_checkpoint = count
        records = iter_chunk_embedding_records(
            database,
            max_characters=max_characters,
            start_after_chunk_id=last_chunk_id,
        )
        if reuse is None:
            batches: Iterable[tuple[list[ChunkEmbeddingRecord], np.ndarray, list[int | None]]] = (
                (batch, vectors, [None] * len(batch))
                for batch, vectors in _embedded_batches(
                    records, provider, batch_size=batch_size, workers=embedding_workers
                )
            )
        else:
            batches = _reuse_aware_batches(
                records,
                provider,
                reuse,
                batch_size=batch_size,
                workers=embedding_workers,
            )
        for batch, vectors, reused_from in batches:
            if vectors.shape != (len(batch), provider.dimensions):
                raise RuntimeError(f"Embedding provider returned an unexpected shape: {vectors.shape}")
            vectors = np.ascontiguousarray(vectors, dtype=np.float32)
            raw_stream.write(vectors.tobytes(order="C"))
            connection.executemany(
                "INSERT INTO vector_chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        count + offset,
                        record.chunk_instance_id,
                        record.content_id,
                        record.document_id,
                        embedding_text_sha256(record.embedding_text),
                        reuse.generation if prior is not None and reuse is not None else None,
                        prior,
                    )
                    for offset, (record, prior) in enumerate(zip(batch, reused_from, strict=True))
                ),
            )
            batch_reused = sum(value is not None for value in reused_from)
            reused_count += batch_reused
            embedded_count += len(batch) - batch_reused
            count += len(batch)
            last_chunk_id = batch[-1].chunk_instance_id
            if count - last_checkpoint >= checkpoint_interval:
                state = _checkpoint(
                    directory,
                    {**state, "chunks_reused": reused_count, "chunks_embedded": embedded_count},
                    raw_stream,
                    connection,
                    count,
                    last_chunk_id,
                )
                last_checkpoint = count
                if progress is not None:
                    progress(count, expected_chunks)
        state = _checkpoint(
            directory,
            {**state, "chunks_reused": reused_count, "chunks_embedded": embedded_count},
            raw_stream,
            connection,
            count,
            last_chunk_id,
        )
        if progress is not None and count != last_checkpoint:
            progress(count, expected_chunks)
        if count != expected_chunks:
            raise RuntimeError(f"Source chunk count changed: expected {expected_chunks}, indexed {count}")
        final_stat = database.stat()
        if (final_stat.st_size, final_stat.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise RuntimeError("Source database changed during chunk semantic construction")

        build_metadata = {
            "schema_version": 1,
            "metadata_schema_version": CHUNK_METADATA_SCHEMA_VERSION,
            "representation": CHUNK_REPRESENTATION,
            "representation_configuration": representation_configuration,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "chunk_count": count,
            "document_count": source_documents,
            "dimensions": provider.dimensions,
            "provider": state["provider"],
            "embedding_execution": state["embedding_execution"],
            "source_database": source_identity["database"],
            "source_database_bytes": source_identity["bytes"],
            "source_database_mtime_ns": source_identity["mtime_ns"],
            "source_schema_version": source_identity["schema_version"],
            "source_build_id": source_identity["build_id"],
            "index_configuration": {"type": "IndexFlatIP", "metric": "cosine_on_l2_normalized_vectors"},
            "checkpoint_configuration": {
                "format": "float32-row-major",
                "interval_chunks": checkpoint_interval,
                "resume_supported": True,
            },
            "reuse": {
                "enabled": reuse is not None,
                "base": reuse_identity,
                "chunks_reused": reused_count,
                "chunks_embedded": embedded_count,
                "reuse_rate": round(reused_count / count, 8),
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
        if reuse is not None:
            reuse.assert_unchanged()
            reuse.close()
            reuse = None

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
                _checkpoint(directory, state, raw_stream, connection, count, last_chunk_id)
            except BaseException:
                pass
        if raw_stream is not None:
            raw_stream.close()
        if connection is not None:
            connection.close()
        if reuse is not None:
            reuse.close()
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
    return load_chunk_vector_manifest(directory)


def _citation(item: Mapping[str, Any]) -> str:
    headings = item.get("heading_path") or []
    section = f" § {' > '.join(str(part) for part in headings)}" if headings else ""
    version = item.get("source_version") or item.get("source_timestamp")
    provenance = f" ({version})" if version else ""
    source = f" {item['source_url']}" if item.get("source_url") else ""
    return f"{item['corpus']} — {item['title']}{section}{provenance}{source}"


class ChunkVectorIndex:
    """Read-only chunk FAISS index that returns the best passage per document."""

    def __init__(self, directory: Path, database: Path | None = None) -> None:
        self.directory = directory.resolve()
        self.manifest = load_chunk_vector_manifest(self.directory)
        self.database = (database or Path(str(self.manifest["source_database"]))).resolve()
        source_metadata = read_index_metadata(self.database)
        if str(self.database) != str(self.manifest.get("source_database")):
            raise ValueError("Chunk vector index is bound to a different source database")
        if source_metadata.get("build_id") != self.manifest.get("source_build_id"):
            raise ValueError("Chunk vector source build ID does not match")
        self.index = faiss.read_index(str(self.directory / self.manifest["files"]["faiss"]["name"]))
        self.connection = _connect_read_only(
            self.directory / self.manifest["files"]["metadata"]["name"], thread_safe=True
        )
        self.source_connection = _connect_read_only(self.database, thread_safe=True)
        self._search_lock = threading.Lock()
        if self.index.ntotal != int(self.manifest["chunk_count"]):
            self.close()
            raise RuntimeError("Loaded chunk FAISS count does not match its manifest")

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None  # type: ignore[assignment]
        if getattr(self, "source_connection", None) is not None:
            self.source_connection.close()
            self.source_connection = None  # type: ignore[assignment]

    def __enter__(self) -> ChunkVectorIndex:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query_vector: np.ndarray, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.shape != (self.index.d,):
            raise ValueError(f"Expected query vector shape {(self.index.d,)}, got {vector.shape}")
        candidate_count = min(self.index.ntotal, min(20_000, max(256, limit * 64)))
        with self._search_lock:
            scores, identifiers = self.index.search(
                np.ascontiguousarray(vector.reshape(1, -1), dtype=np.float32), candidate_count
            )
            ordered_ids = [int(value) for value in identifiers[0] if int(value) >= 0]
            if not ordered_ids:
                return []
            placeholders = ",".join("?" for _ in ordered_ids)
            metadata_rows = self.connection.execute(
                f"SELECT * FROM vector_chunks WHERE vector_id IN ({placeholders})", ordered_ids
            ).fetchall()
            by_vector = {int(row["vector_id"]): dict(row) for row in metadata_rows}
            chunk_ids = [str(by_vector[vector_id]["chunk_instance_id"]) for vector_id in ordered_ids]
            chunk_placeholders = ",".join("?" for _ in chunk_ids)
            source_rows = self.source_connection.execute(
                f"""
                SELECT c.chunk_instance_id AS chunk_id, c.content_id, c.document_id,
                       c.ordinal, c.heading_path, c.text, c.attributes_json,
                       d.corpus, d.title, d.source_url, d.source_version, d.source_timestamp
                FROM chunks c JOIN documents d ON d.document_id = c.document_id
                WHERE c.chunk_instance_id IN ({chunk_placeholders})
                """,
                chunk_ids,
            ).fetchall()
        by_chunk = {str(row["chunk_id"]): dict(row) for row in source_rows}
        results: list[dict[str, Any]] = []
        seen_documents: set[str] = set()
        for chunk_rank, (vector_id, score) in enumerate(zip(ordered_ids, scores[0], strict=True), start=1):
            vector_row = by_vector[vector_id]
            item = by_chunk.get(str(vector_row["chunk_instance_id"]))
            if item is None or str(item["document_id"]) in seen_documents:
                continue
            seen_documents.add(str(item["document_id"]))
            attributes = json.loads(item.pop("attributes_json"))
            item["heading_path"] = list(_heading_parts(str(item["heading_path"])))
            item["revision_timestamp"] = attributes.get("revision_timestamp") or item["source_timestamp"]
            item["section_index"] = attributes.get("section_index")
            item["chunk_index"] = attributes.get("chunk_index")
            item["raw_score"] = float(score)
            item["score"] = float(score)
            item["semantic_rank"] = len(results) + 1
            item["semantic_chunk_rank"] = chunk_rank
            item["ranking_reason"] = "semantic_chunk"
            item["citation"] = _citation(item)
            results.append(item)
            if len(results) >= limit:
                break
        return results


def semantic_search(
    vector_index: ChunkVectorIndex,
    provider: EmbeddingProvider,
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if provider.dimensions != vector_index.index.d:
        raise ValueError("Embedding dimensions do not match the chunk vector index")
    return vector_index.search(provider.embed_query(query), limit)


def _progress(count: int, total: int) -> None:
    print(_json({"indexed": count, "total": total, "percent": round(count / total * 100, 2)}), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query chunk-level semantic indexes.")
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
    build.add_argument("--max-characters", type=int, default=4_000)
    build.add_argument("--reuse-from", type=Path)
    build.add_argument("--skip-reuse-checksums", action="store_true")
    build.add_argument("--overwrite", action="store_true")
    build.add_argument("--resume", action="store_true")
    build.add_argument("--restart", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--index", type=Path, required=True)
    verify.add_argument("--database", type=Path)
    verify.add_argument("--skip-checksums", action="store_true")
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
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        result = verify_chunk_vector_index(
            args.index, database=args.database, verify_checksums=not args.skip_checksums
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    config = load_embedding_model_config(args.models, args.model_id)
    provider = OllamaEmbeddingClient(config, base_url=args.ollama_url)
    if args.command == "build":
        result = build_chunk_vector_index(
            args.database,
            args.output,
            provider,
            overwrite=args.overwrite,
            resume=args.resume,
            restart=args.restart,
            batch_size=args.batch_size,
            embedding_workers=args.embedding_workers,
            checkpoint_interval=args.checkpoint_interval,
            max_characters=args.max_characters,
            reuse_from=args.reuse_from,
            verify_reuse_checksums=not args.skip_reuse_checksums,
            progress=_progress,
        )
    else:
        with ChunkVectorIndex(args.index, args.database) as index:
            if args.command == "query":
                if args.mode == "semantic":
                    result = {"results": semantic_search(index, provider, args.query, limit=args.limit)}
                else:
                    result = hybrid_search(args.database, index, provider, args.query, limit=args.limit)
            else:
                identity = {
                    "database": str(args.database.resolve()),
                    "vector_directory": str(args.index.resolve()),
                    "vector_manifest": index.manifest,
                }
                result: dict[str, Any] = {}
                if args.mode == "all":
                    result["bm25"] = evaluate(args.database, args.suite)
                if args.mode in {"semantic", "all"}:
                    result["semantic"] = evaluate_retriever(
                        args.suite,
                        lambda query, limit, _mode: semantic_search(index, provider, query, limit=limit),
                        retrieval_identity={"retriever": "faiss_chunk_semantic", **identity},
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
                        retrieval_identity={"retriever": "chunk_hybrid_rrf", **identity},
                    )
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
