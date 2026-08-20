from __future__ import annotations

import json
import math
import time
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
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
            raise ValueError("timeout_seconds must be positive and finite")
        if not 0 <= max_retries <= 10:
            raise ValueError("max_retries must be between 0 and 10")
        if retry_backoff_seconds < 0 or not math.isfinite(retry_backoff_seconds):
            raise ValueError("retry_backoff_seconds must be nonnegative and finite")
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

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
        value: Any = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    value = json.load(response)
                break
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                transient_runner_failure = error.code == 400 and any(
                    marker in detail.casefold()
                    for marker in ("connection refused", "actively refused", "/tokenize", "/embedding")
                )
                retryable = error.code in {408, 409, 425, 429} or error.code >= 500 or transient_runner_failure
                if not retryable or attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Ollama embedding request failed with HTTP {error.code} after {attempt + 1} attempt(s): {detail}"
                    ) from error
            except URLError as error:
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Ollama embedding endpoint is unavailable at {self.base_url} after "
                        f"{attempt + 1} attempt(s): {error.reason}"
                    ) from error
            if self.retry_backoff_seconds:
                time.sleep(self.retry_backoff_seconds * (2**attempt))
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
