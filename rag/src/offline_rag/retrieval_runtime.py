from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .bm25 import read_index_metadata
from .chunk_vector_index import CHUNK_REPRESENTATION, ChunkVectorIndex
from .embeddings import EmbeddingProvider
from .retrieval import index_status, search_documents
from .vector_index import VectorIndex, hybrid_search, load_vector_manifest, semantic_search


RETRIEVAL_MODES = ("bm25", "semantic", "hybrid")


class RetrievalUnavailableError(RuntimeError):
    """Raised when an optional retrieval backend is configured but unavailable."""


class CachedEmbeddingProvider:
    """Thread-safe bounded LRU around query embeddings from a local provider."""

    def __init__(self, provider: EmbeddingProvider, maximum_queries: int = 256) -> None:
        if not 0 <= maximum_queries <= 4096:
            raise ValueError("query cache size must be between 0 and 4096")
        self.provider = provider
        self.dimensions = provider.dimensions
        self.maximum_queries = maximum_queries
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def provider_metadata(self) -> dict[str, object]:
        return dict(self.provider.provider_metadata)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self.provider.embed_documents(texts)

    def embed_query(self, query: str) -> np.ndarray:
        with self._lock:
            cached = self._cache.get(query)
            if cached is not None:
                self._cache.move_to_end(query)
                self._hits += 1
                return cached.copy()
            self._misses += 1
        vector = np.asarray(self.provider.embed_query(query), dtype=np.float32)
        if self.maximum_queries:
            with self._lock:
                existing = self._cache.get(query)
                if existing is None:
                    self._cache[query] = vector.copy()
                    while len(self._cache) > self.maximum_queries:
                        self._cache.popitem(last=False)
                else:
                    vector = existing
                    self._cache.move_to_end(query)
        return vector.copy()

    def status(self) -> dict[str, int]:
        with self._lock:
            return {
                "capacity": self.maximum_queries,
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
            }


class RetrievalRuntime:
    """One BM25 database with an optional lazily loaded semantic generation."""

    def __init__(
        self,
        database: Path,
        *,
        vector_directory: Path | None = None,
        provider_factory: Callable[[], EmbeddingProvider] | None = None,
        default_mode: str = "bm25",
        query_cache_size: int = 256,
    ) -> None:
        if default_mode not in RETRIEVAL_MODES:
            raise ValueError(f"default retrieval mode must be one of: {', '.join(RETRIEVAL_MODES)}")
        if not 0 <= query_cache_size <= 4096:
            raise ValueError("query cache size must be between 0 and 4096")
        self.database = database.resolve()
        self.lexical_status = index_status(self.database)
        self.vector_directory = vector_directory.resolve() if vector_directory is not None else None
        self.provider_factory = provider_factory
        self.default_mode = default_mode
        self.query_cache_size = query_cache_size
        self._load_lock = threading.Lock()
        self._vector_index: VectorIndex | ChunkVectorIndex | None = None
        self._provider: CachedEmbeddingProvider | None = None
        self._last_load_error: str | None = None
        self._last_query_error: str | None = None
        if self.vector_directory is None and default_mode != "bm25":
            raise ValueError("semantic or hybrid default mode requires a vector directory")
        if self.vector_directory is not None and provider_factory is None:
            raise ValueError("a semantic vector directory requires an embedding provider factory")
        if default_mode != "bm25" and not self._semantic_published():
            raise FileNotFoundError(f"Published semantic manifest not found: {self.vector_directory}")

    def _semantic_published(self) -> bool:
        return self.vector_directory is not None and (self.vector_directory / "manifest.json").is_file()

    def _load_semantic(self) -> tuple[VectorIndex | ChunkVectorIndex, CachedEmbeddingProvider]:
        if self._vector_index is not None and self._provider is not None:
            return self._vector_index, self._provider
        with self._load_lock:
            if self._vector_index is not None and self._provider is not None:
                return self._vector_index, self._provider
            if not self._semantic_published() or self.vector_directory is None or self.provider_factory is None:
                raise RetrievalUnavailableError("semantic retrieval has no verified published generation")
            vector_index: VectorIndex | ChunkVectorIndex | None = None
            try:
                manifest = load_vector_manifest(self.vector_directory)
                source_metadata = read_index_metadata(self.database)
                if str(manifest.get("source_database")) != str(self.database):
                    raise ValueError("semantic generation is bound to a different BM25 database")
                if manifest.get("source_build_id") != source_metadata.get("build_id"):
                    raise ValueError("semantic generation source build ID does not match BM25")
                resolved_provider = self.provider_factory()
                provider = (
                    resolved_provider
                    if isinstance(resolved_provider, CachedEmbeddingProvider)
                    else CachedEmbeddingProvider(resolved_provider, self.query_cache_size)
                )
                if int(manifest["dimensions"]) != provider.dimensions:
                    raise ValueError("semantic generation dimensions do not match the embedding provider")
                if manifest.get("provider") != provider.provider_metadata:
                    raise ValueError("semantic generation provider identity does not match configuration")
                if manifest.get("representation") == CHUNK_REPRESENTATION:
                    vector_index = ChunkVectorIndex(self.vector_directory, self.database)
                else:
                    vector_index = VectorIndex(self.vector_directory)
                self._vector_index = vector_index
                self._provider = provider
                self._last_load_error = None
                return vector_index, provider
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
                if vector_index is not None:
                    vector_index.close()
                self._last_load_error = str(error)
                raise RetrievalUnavailableError(str(error)) from error

    def search(
        self,
        query: str,
        *,
        limit: int,
        query_mode: str,
        retrieval_mode: str | None = None,
        candidate_limit: int = 100,
    ) -> dict[str, Any]:
        selected = retrieval_mode or self.default_mode
        if selected not in RETRIEVAL_MODES:
            raise ValueError(f"retrieval_mode must be one of: {', '.join(RETRIEVAL_MODES)}")
        started = time.perf_counter()
        if selected == "bm25":
            response = search_documents(
                self.database,
                query,
                limit=limit,
                mode=query_mode,
                candidate_limit=candidate_limit,
            )
            response.setdefault("retriever", "sqlite_fts5_bm25")
        else:
            vector_index, provider = self._load_semantic()
            try:
                if selected == "semantic":
                    response = {
                        "query": query,
                        "mode": query_mode,
                        "ranking_unit": "document",
                        "retriever": "faiss_semantic",
                        "results": semantic_search(vector_index, provider, query, limit=limit),
                    }
                else:
                    response = hybrid_search(
                        self.database,
                        vector_index,
                        provider,
                        query,
                        limit=limit,
                        mode=query_mode,
                        lexical_candidates=max(candidate_limit, limit),
                        semantic_candidates=max(candidate_limit, limit),
                    )
                self._last_query_error = None
            except (OSError, RuntimeError) as error:
                self._last_query_error = str(error)
                raise RetrievalUnavailableError(str(error)) from error
        response["retrieval_mode"] = selected
        response["latency_ms"] = round((time.perf_counter() - started) * 1_000, 3)
        return response

    def status(self) -> dict[str, Any]:
        published = self._semantic_published()
        published_manifest: dict[str, Any] | None = None
        if published and self.vector_directory is not None:
            try:
                published_manifest = load_vector_manifest(self.vector_directory)
            except (FileNotFoundError, OSError, ValueError) as error:
                self._last_load_error = str(error)
        available = ["bm25"]
        if published_manifest is not None and self.provider_factory is not None:
            available.extend(("semantic", "hybrid"))
        provider = self._provider
        return {
            "default_mode": self.default_mode,
            "available_modes": available,
            "bm25_ready": True,
            "semantic": {
                "configured": self.vector_directory is not None,
                "published": published_manifest is not None,
                "loaded": self._vector_index is not None,
                "directory": str(self.vector_directory) if self.vector_directory is not None else None,
                "representation": (
                    self._vector_index.manifest.get("representation", "document-title-lead")
                    if self._vector_index is not None
                    else (
                        published_manifest.get("representation", "document-title-lead")
                        if published_manifest is not None
                        else None
                    )
                ),
                "vector_count": (
                    published_manifest.get("chunk_count", published_manifest.get("document_count"))
                    if published_manifest is not None
                    else None
                ),
                "last_load_error": self._last_load_error,
                "last_query_error": self._last_query_error,
                "query_cache": provider.status()
                if provider is not None
                else {"capacity": self.query_cache_size, "entries": 0, "hits": 0, "misses": 0},
            },
        }

    def close(self) -> None:
        with self._load_lock:
            if self._vector_index is not None:
                self._vector_index.close()
            self._vector_index = None
            self._provider = None
