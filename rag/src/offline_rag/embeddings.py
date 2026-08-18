from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class EmbeddingModelConfig:
    """Resolved embedding settings from the repository model registry."""

    model_id: str
    runtime_model: str
    dimensions: int
    query_instruction: str | None


class EmbeddingProvider(Protocol):
    """Small provider-neutral interface used by vector indexing and search."""

    @property
    def dimensions(self) -> int: ...

    @property
    def provider_metadata(self) -> Mapping[str, object]: ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, query: str) -> np.ndarray: ...


def load_embedding_model_config(path: Path, model_id: str | None = None) -> EmbeddingModelConfig:
    """Resolve one embedding model, defaulting to the registry's highest priority."""

    value = json.loads(path.read_text(encoding="utf-8"))
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, list):
        raise ValueError(f"Model registry has no models list: {path}")
    embedding_models = [item for item in models if isinstance(item, dict) and item.get("role") == "embedding"]
    if model_id is None:
        matches = sorted(embedding_models, key=lambda item: (int(item.get("priority", 1_000_000)), str(item.get("id"))))
    else:
        matches = [item for item in embedding_models if item.get("id") == model_id]
    if not matches:
        label = model_id if model_id is not None else "role=embedding"
        raise KeyError(f"No configured model matches: {label}")
    item = matches[0]
    resolved_id = str(item.get("id") or "")
    if not resolved_id:
        raise ValueError("Embedding model has no id")
    runtime_model = item.get("ollama_model")
    dimensions = item.get("embedding_dimensions")
    if not isinstance(runtime_model, str) or not runtime_model:
        raise ValueError(f"Embedding model {resolved_id!r} has no ollama_model")
    if not isinstance(dimensions, int) or dimensions < 1:
        raise ValueError(f"Embedding model {resolved_id!r} has invalid embedding_dimensions")
    instruction = item.get("query_instruction")
    if instruction is not None and (not isinstance(instruction, str) or not instruction.strip()):
        raise ValueError(f"Embedding model {resolved_id!r} has an invalid query_instruction")
    return EmbeddingModelConfig(resolved_id, runtime_model, dimensions, instruction)


def normalize_rows(vectors: np.ndarray, expected_dimensions: int) -> np.ndarray:
    """Validate and L2-normalize a float32 vector matrix."""

    values = np.ascontiguousarray(vectors, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != expected_dimensions:
        raise ValueError(
            f"Expected a two-dimensional embedding matrix with {expected_dimensions} columns; got {values.shape}"
        )
    if not np.isfinite(values).all():
        raise ValueError("Embedding response contains a non-finite value")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms <= 0) or not np.isfinite(norms).all():
        raise ValueError("Embedding response contains a zero-length vector")
    return np.ascontiguousarray(values / norms, dtype=np.float32)


class OllamaEmbeddingClient:
    """Batch embedding client for Ollama's local `/api/embed` endpoint."""

    def __init__(
        self,
        config: EmbeddingModelConfig,
        *,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout_seconds: float = 300.0,
        keep_alive: str = "10m",
    ) -> None:
        if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
            raise ValueError("timeout_seconds must be positive and finite")
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive

    @property
    def dimensions(self) -> int:
        return self.config.dimensions

    @property
    def provider_metadata(self) -> Mapping[str, object]:
        return {
            "provider": "ollama",
            "model_id": self.config.model_id,
            "runtime_model": self.config.runtime_model,
            "dimensions": self.config.dimensions,
            "query_instruction": self.config.query_instruction,
        }

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding inputs must be nonempty strings")
        payload = json.dumps(
            {
                "model": self.config.runtime_model,
                "input": list(texts),
                "dimensions": self.dimensions,
                "keep_alive": self.keep_alive,
                "truncate": True,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value: Any = json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama embedding request failed with HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Ollama embedding endpoint is unavailable at {self.base_url}: {error.reason}") from error
        embeddings = value.get("embeddings") if isinstance(value, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama returned {len(embeddings) if isinstance(embeddings, list) else 'invalid'} vectors "
                f"for {len(texts)} inputs"
            )
        return normalize_rows(np.asarray(embeddings, dtype=np.float32), self.dimensions)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(self, query: str) -> np.ndarray:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if self.config.query_instruction:
            query = f"Instruct: {self.config.query_instruction}\nQuery: {query}"
        return self._embed([query])[0]
