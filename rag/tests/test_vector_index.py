from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_archive
from offline_rag.bm25 import build_index
from offline_rag.embeddings import load_embedding_model_config, normalize_rows
from offline_rag.vector_index import (
    VectorIndex,
    build_vector_index,
    hybrid_search,
    iter_document_embedding_records,
    load_vector_manifest,
    semantic_search,
)
from offline_rag.wikipedia_dump import extract


class FakeEmbeddingProvider:
    dimensions = 5

    @property
    def provider_metadata(self) -> dict[str, object]:
        return {"provider": "fake", "model_id": "test-embedding", "dimensions": self.dimensions}

    def _vectors(self, texts: list[str]) -> np.ndarray:
        vectors = []
        groups = (
            ("apollo", "lunar", "moon", "rope memory", "guidance computer"),
            ("reciprocal", "fusion", "ranking"),
            ("c++", "cpp", "std::vector", "programming"),
            ("redirect",),
        )
        for text in texts:
            lowered = text.casefold()
            vector = [float(any(term in lowered for term in group)) for group in groups]
            vector.append(0.01)
            vectors.append(vector)
        return normalize_rows(np.asarray(vectors, dtype=np.float32), self.dimensions)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._vectors(texts)

    def embed_query(self, query: str) -> np.ndarray:
        return self._vectors([query])[0]


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("intentional provider failure")


class FailAfterOneEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("interrupted after one batch")
        return super().embed_documents(texts)


class OutOfOrderEmbeddingProvider(FakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if texts and "Apollo Guidance Computer" in texts[0]:
            time.sleep(0.02)
        return super().embed_documents(texts)


class VectorIndexTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        build_index(processed, database)
        return database, root / "vectors"

    def test_model_registry_and_normalization(self):
        root = Path(__file__).resolve().parents[2]
        config = load_embedding_model_config(root / "config" / "models.json", "qwen3-embedding-0.6b")
        self.assertEqual(config.runtime_model, "qwen3-embedding:0.6b")
        self.assertEqual(config.dimensions, 256)
        values = normalize_rows(np.asarray([[3.0, 4.0]], dtype=np.float32), 2)
        self.assertAlmostEqual(float(np.linalg.norm(values[0])), 1.0, places=6)
        with self.assertRaises(ValueError):
            normalize_rows(np.zeros((1, 2), dtype=np.float32), 2)

    def test_document_stream_resumes_strictly_after_last_id(self):
        with tempfile.TemporaryDirectory() as directory:
            database, _ = self.prepare(Path(directory))
            all_records = list(iter_document_embedding_records(database, max_chunks=2))
            resumed = list(
                iter_document_embedding_records(
                    database,
                    max_chunks=2,
                    start_after_document_id=all_records[0].document_id,
                )
            )
            self.assertEqual([record.document_id for record in resumed], [record.document_id for record in all_records[1:]])
            self.assertTrue(all(record.embedding_text.startswith(record.title) for record in all_records))

    def test_vector_build_search_and_manifest_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            provider = OutOfOrderEmbeddingProvider()
            result = build_vector_index(database, destination, provider, batch_size=1, embedding_workers=2)
            self.assertEqual(result["document_count"], 2)
            self.assertEqual(result["source_document_count"], 3)
            self.assertEqual(result["dimensions"], 5)
            self.assertEqual(load_vector_manifest(destination)["generation"], result["generation"])
            with VectorIndex(destination) as index:
                results = semantic_search(index, provider, "lunar navigation", limit=3)
            self.assertEqual(results[0]["document_id"], "enwiki:100")
            self.assertIn("Wikipedia — Apollo Guidance Computer", results[0]["citation"])
            self.assertEqual(results[0]["ranking_reason"], "semantic")

    def test_existing_generation_requires_overwrite_and_failed_rebuild_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            build_vector_index(database, destination, FakeEmbeddingProvider(), batch_size=2)
            before = (destination / "manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                build_vector_index(database, destination, FakeEmbeddingProvider(), batch_size=2)
            with self.assertRaisesRegex(RuntimeError, "intentional provider failure"):
                build_vector_index(database, destination, FailingEmbeddingProvider(), batch_size=2, overwrite=True)
            self.assertEqual((destination / "manifest.json").read_bytes(), before)
            self.assertEqual(load_vector_manifest(destination)["document_count"], 2)

    def test_interrupted_build_resumes_from_consistent_vector_metadata_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "interrupted after one batch"):
                build_vector_index(
                    database,
                    destination,
                    FailAfterOneEmbeddingProvider(),
                    batch_size=1,
                    embedding_workers=1,
                    checkpoint_interval=1,
                )
            state_path = destination / ".build-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["completed_documents"], 1)
            raw = destination / state["raw_vectors_file"]
            self.assertEqual(raw.stat().st_size, 5 * 4)

            # Simulate a crash after extra vector bytes reached disk but before
            # their SQLite row committed. Resume must truncate the raw tail.
            with raw.open("ab") as stream:
                stream.write(np.ones(5, dtype=np.float32).tobytes())
            result = build_vector_index(
                database,
                destination,
                FakeEmbeddingProvider(),
                resume=True,
                batch_size=1,
                embedding_workers=1,
                checkpoint_interval=1,
            )
            self.assertEqual(result["document_count"], 2)
            self.assertFalse(state_path.exists())
            self.assertFalse(raw.exists())
            with VectorIndex(destination) as index:
                self.assertEqual(
                    semantic_search(index, FakeEmbeddingProvider(), "lunar navigation", limit=2)[0]["document_id"],
                    "enwiki:100",
                )

    def test_checkpoint_mismatch_is_rejected_and_restart_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "interrupted after one batch"):
                build_vector_index(
                    database,
                    destination,
                    FailAfterOneEmbeddingProvider(),
                    batch_size=1,
                    embedding_workers=1,
                )
            with self.assertRaisesRegex(ValueError, "embedding_execution"):
                build_vector_index(
                    database,
                    destination,
                    FakeEmbeddingProvider(),
                    resume=True,
                    batch_size=2,
                    embedding_workers=1,
                )
            result = build_vector_index(
                database,
                destination,
                FakeEmbeddingProvider(),
                restart=True,
                batch_size=2,
                embedding_workers=1,
            )
            self.assertEqual(result["document_count"], 2)

    def test_hybrid_fusion_returns_provenance_and_both_ranks(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            build_vector_index(database, destination, FakeEmbeddingProvider(), batch_size=2)
            with VectorIndex(destination) as index:
                result = hybrid_search(
                    database,
                    index,
                    FakeEmbeddingProvider(),
                    "Apollo Guidance Computer",
                    limit=2,
                    lexical_candidates=10,
                    semantic_candidates=3,
                )
            self.assertEqual(result["results"][0]["document_id"], "enwiki:100")
            self.assertEqual(result["results"][0]["ranking_reason"], "hybrid_rrf")
            self.assertEqual(result["results"][0]["fusion"]["lexical_rank"], 1)
            self.assertEqual(result["results"][0]["fusion"]["semantic_rank"], 1)

    def test_manifest_rejects_modified_generation_file(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            manifest = build_vector_index(database, destination, FakeEmbeddingProvider(), batch_size=2)
            metadata = destination / manifest["files"]["metadata"]["name"]
            metadata.write_bytes(metadata.read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                load_vector_manifest(destination)


if __name__ == "__main__":
    unittest.main()
