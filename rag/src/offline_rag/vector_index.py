from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
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
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def iter_document_embedding_records(
    database: Path,
    *,
    max_chunks: int = 2,
    max_characters: int = 8_000,
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
                FROM documents d
                JOIN chunks c ON c.document_id = d.document_id
                WHERE c.ordinal < ?
                ORDER BY d.document_id, c.ordinal, c.row_id
                """,
                (max_chunks,),
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
                ORDER BY d.document_id, c.section_index, c.chunk_index, c.row_id
                """
            )
        current_id: str | None = None
        document: dict[str, Any] | None = None
        chunks: list[str] = []
        for row in rows:
            document_id = str(row["document_id"])
            if current_id is not None and document_id != current_id:
                assert document is not None
                combined = "\n\n".join(chunks)[:max_characters]
                yield DocumentEmbeddingRecord(embedding_text=f"{document['title']}\n\n{combined}", **document)
                chunks = []
            if document_id != current_id:
                current_id = document_id
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
            if int(row["ordinal"]) < max_chunks:
                chunks.append(str(row["text"]))
        if document is not None:
            combined = "\n\n".join(chunks)[:max_characters]
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
    batch_size: int = 128,
    embedding_workers: int = 2,
    max_chunks: int = 2,
    max_characters: int = 8_000,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Build a document-level cosine index and atomically publish its manifest."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not 1 <= embedding_workers <= 8:
        raise ValueError("embedding_workers must be between 1 and 8")
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
    previous: dict[str, Any] | None = None
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.exists():
        if not overwrite:
            raise FileExistsError(f"Vector index already exists: {directory}; authorize overwrite explicitly")
        previous = load_vector_manifest(directory)

    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    final_faiss = directory / f"vectors-{generation}.faiss"
    final_metadata = directory / f"metadata-{generation}.sqlite3"
    temporary_faiss = directory / f".{final_faiss.name}.building"
    temporary_metadata = directory / f".{final_metadata.name}.building"
    index = faiss.IndexFlatIP(provider.dimensions)
    connection: sqlite3.Connection | None = None
    started = time.monotonic()
    count = 0
    published_files = False
    manifest_published = False
    try:
        connection = sqlite3.connect(temporary_metadata)
        connection.executescript(METADATA_SCHEMA)
        records = iter_document_embedding_records(
            database,
            max_chunks=max_chunks,
            max_characters=max_characters,
        )
        insert_sql = "INSERT INTO vector_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        for batch, vectors in _embedded_batches(
            records,
            provider,
            batch_size=batch_size,
            workers=embedding_workers,
        ):
            if vectors.shape != (len(batch), provider.dimensions):
                raise RuntimeError(f"Embedding provider returned an unexpected shape: {vectors.shape}")
            index.add(np.ascontiguousarray(vectors, dtype=np.float32))
            connection.executemany(insert_sql, _metadata_rows(batch, count))
            count += len(batch)
            if count % max(batch_size, 256) == 0:
                connection.commit()
                if progress is not None:
                    progress(count, expected_documents)
        connection.commit()
        if count != expected_documents:
            raise RuntimeError(f"Source document count changed: expected {expected_documents}, indexed {count}")
        final_source_stat = database.stat()
        if (final_source_stat.st_size, final_source_stat.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise RuntimeError("Source database changed during semantic index construction")
        build_metadata = {
            "schema_version": VECTOR_SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "document_count": count,
            "source_document_count": source_document_count,
            "dimensions": provider.dimensions,
            "provider": dict(provider.provider_metadata),
            "embedding_execution": {"batch_size": batch_size, "workers": embedding_workers},
            "source_database": str(database.resolve()),
            "source_database_bytes": source_stat.st_size,
            "source_database_mtime_ns": source_stat.st_mtime_ns,
            "source_schema_version": source_metadata.get("schema_version", 1),
            "source_build_id": source_metadata.get("build_id"),
            "content_configuration": {"max_chunks": max_chunks, "max_characters": max_characters},
            "index_configuration": {"type": "IndexFlatIP", "metric": "cosine_on_l2_normalized_vectors"},
        }
        connection.executemany(
            "INSERT INTO vector_metadata(key, value_json) VALUES (?, ?)",
            ((key, _json(value)) for key, value in sorted(build_metadata.items())),
        )
        connection.commit()
        connection.close()
        connection = None
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
        if connection is not None:
            connection.close()
        for path in (temporary_faiss, temporary_metadata):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if published_files and not manifest_published:
            for path in (final_faiss, final_metadata):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise

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
    build.add_argument("--max-chunks", type=int, default=2)
    build.add_argument("--max-characters", type=int, default=8_000)
    build.add_argument("--overwrite", action="store_true")
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
    config = load_embedding_model_config(args.models, args.model_id)
    provider = OllamaEmbeddingClient(config, base_url=args.ollama_url)
    if args.command == "build":
        result = build_vector_index(
            args.database,
            args.output,
            provider,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
            embedding_workers=args.embedding_workers,
            max_chunks=args.max_chunks,
            max_characters=args.max_characters,
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
