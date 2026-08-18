from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index
from offline_rag.corpus_update import plan_vector_update
from offline_rag.embeddings import normalize_rows
from offline_rag.records import make_content_id
from offline_rag.vector_index import VectorIndex, build_vector_index, verify_vector_index


class CountingEmbeddingProvider:
    dimensions = 4

    def __init__(self) -> None:
        self.embedded_texts: list[str] = []

    @property
    def provider_metadata(self) -> dict[str, object]:
        return {"provider": "fake", "model_id": "incremental-test", "dimensions": self.dimensions}

    def _vectors(self, texts: list[str]) -> np.ndarray:
        values = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values.append([float(digest[index] + 1) for index in range(self.dimensions)])
        return normalize_rows(np.asarray(values, dtype=np.float32), self.dimensions)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.embedded_texts.extend(texts)
        return self._vectors(texts)

    def embed_query(self, query: str) -> np.ndarray:
        return self._vectors([query])[0]


class FailOnSecondCallProvider(CountingEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("intentional incremental interruption")
        return super().embed_documents(texts)


def _write_corpus(directory: Path, version: str, values: list[tuple[str, str, str]]) -> Path:
    directory.mkdir(parents=True)
    documents = []
    chunks = []
    for document_id, title, text in values:
        documents.append(
            {
                "schema_version": 1,
                "document_id": document_id,
                "corpus": "wikipedia-en",
                "title": title,
                "source_url": f"https://example.test/{document_id}",
                "source_version": version,
                "source_timestamp": f"{version[:4]}-{version[4:6]}-{version[6:]}T00:00:00Z",
                "license": "CC-BY-SA-4.0",
                "attributes": {},
            }
        )
        chunks.append(
            {
                "schema_version": 1,
                "chunk_instance_id": f"{document_id}:{version}:0",
                "content_id": make_content_id(text),
                "document_id": document_id,
                "parent_chunk_id": None,
                "ordinal": 0,
                "heading_path": [],
                "text": text,
                "character_count": len(text),
                "token_count": None,
                "previous_chunk_id": None,
                "next_chunk_id": None,
                "attributes": {},
            }
        )
    (directory / "documents.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in documents),
        encoding="utf-8",
    )
    (directory / "chunks.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in chunks),
        encoding="utf-8",
    )
    database = directory.parent / f"{directory.name}.sqlite3"
    build_index(directory, database)
    return database


def _prepare_generations(root: Path) -> tuple[Path, Path]:
    previous = _write_corpus(
        root / "previous-corpus",
        "20260801",
        [
            ("enwiki:100", "Alpha", "unchanged lead text"),
            ("enwiki:102", "Beta", "old beta text"),
            ("enwiki:104", "Removed", "removed article text"),
        ],
    )
    new = _write_corpus(
        root / "new-corpus",
        "20260901",
        [
            ("enwiki:100", "Alpha", "unchanged lead text"),
            ("enwiki:102", "Beta", "revised beta text"),
            ("enwiki:103", "Added", "new article text"),
        ],
    )
    return previous, new


class CorpusUpdateTests(unittest.TestCase):
    def test_plan_classifies_embedding_inputs_with_constant_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            previous, new = _prepare_generations(Path(directory))
            result = plan_vector_update(previous, new, max_chunks=1, max_characters=4000)
            self.assertEqual(
                result["changes"],
                {"unchanged": 1, "modified": 1, "added": 1, "deleted": 1},
            )
            self.assertEqual(result["embedding_work"]["vectors_reusable"], 1)
            self.assertEqual(result["embedding_work"]["vectors_to_embed"], 2)
            self.assertAlmostEqual(result["embedding_work"]["reuse_rate"], 1 / 3, places=8)
            self.assertEqual(result["sample_document_ids"]["unchanged"], ["enwiki:100"])

    def test_incremental_build_reuses_legacy_generation_and_refreshes_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, new = _prepare_generations(root)
            previous_vectors = root / "previous-vectors"
            old_provider = CountingEmbeddingProvider()
            old_manifest = build_vector_index(
                previous,
                previous_vectors,
                old_provider,
                batch_size=2,
                max_chunks=1,
                max_characters=4000,
            )
            self.assertEqual(len(old_provider.embedded_texts), 3)

            # The running production build uses the version-1 metadata layout.
            # Remove the new optional fingerprint table to exercise that exact
            # compatibility path, then refresh its manifest binding.
            metadata_path = previous_vectors / old_manifest["files"]["metadata"]["name"]
            connection = sqlite3.connect(metadata_path)
            connection.execute("DROP TABLE vector_content")
            connection.commit()
            connection.close()
            manifest_path = previous_vectors / "manifest.json"
            old_manifest["files"]["metadata"]["bytes"] = metadata_path.stat().st_size
            old_manifest["files"]["metadata"]["sha256"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(old_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            new_provider = CountingEmbeddingProvider()
            destination = root / "new-vectors"
            result = build_vector_index(
                new,
                destination,
                new_provider,
                reuse_from=previous_vectors,
                batch_size=2,
                embedding_workers=2,
                checkpoint_interval=1,
                max_chunks=1,
                max_characters=4000,
            )
            self.assertEqual(len(new_provider.embedded_texts), 2)
            self.assertTrue(result["reuse"]["enabled"])
            self.assertEqual(result["reuse"]["documents_reused"], 1)
            self.assertEqual(result["reuse"]["documents_embedded"], 2)
            self.assertAlmostEqual(result["reuse"]["reuse_rate"], 1 / 3, places=8)
            self.assertTrue(verify_vector_index(destination, database=new)["source_verified"])
            self.assertTrue(verify_vector_index(previous_vectors, database=previous)["source_verified"])

            with VectorIndex(previous_vectors) as old_index, VectorIndex(destination) as new_index:
                old_vector_id = int(
                    old_index.connection.execute(
                        "SELECT vector_id FROM vector_documents WHERE document_id='enwiki:100'"
                    ).fetchone()[0]
                )
                new_row = new_index.connection.execute(
                    "SELECT vector_id, source_version FROM vector_documents WHERE document_id='enwiki:100'"
                ).fetchone()
                old_vector = old_index.index.reconstruct(old_vector_id)
                new_vector = new_index.index.reconstruct(int(new_row["vector_id"]))
                np.testing.assert_array_equal(old_vector, new_vector)
                self.assertEqual(new_row["source_version"], "20260901")

    def test_incremental_interruption_resumes_with_exact_reuse_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, new = _prepare_generations(root)
            previous_vectors = root / "previous-vectors"
            build_vector_index(
                previous,
                previous_vectors,
                CountingEmbeddingProvider(),
                batch_size=1,
                max_chunks=1,
                max_characters=4000,
            )
            destination = root / "new-vectors"
            with self.assertRaisesRegex(RuntimeError, "intentional incremental interruption"):
                build_vector_index(
                    new,
                    destination,
                    FailOnSecondCallProvider(),
                    reuse_from=previous_vectors,
                    batch_size=1,
                    embedding_workers=1,
                    checkpoint_interval=1,
                    max_chunks=1,
                    max_characters=4000,
                )
            state = json.loads((destination / ".build-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["completed_documents"], 2)
            self.assertEqual(state["documents_reused"], 1)
            self.assertEqual(state["documents_embedded"], 1)

            with self.assertRaisesRegex(ValueError, "requires the original reuse generation"):
                build_vector_index(
                    new,
                    destination,
                    CountingEmbeddingProvider(),
                    resume=True,
                    batch_size=1,
                    embedding_workers=1,
                    checkpoint_interval=1,
                    max_chunks=1,
                    max_characters=4000,
                )

            result = build_vector_index(
                new,
                destination,
                CountingEmbeddingProvider(),
                reuse_from=previous_vectors,
                resume=True,
                batch_size=1,
                embedding_workers=1,
                checkpoint_interval=1,
                max_chunks=1,
                max_characters=4000,
            )
            self.assertEqual(result["reuse"]["documents_reused"], 1)
            self.assertEqual(result["reuse"]["documents_embedded"], 2)
            self.assertFalse((destination / ".build-state.json").exists())

    def test_reuse_rejects_changed_representation_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, new = _prepare_generations(root)
            previous_vectors = root / "previous-vectors"
            build_vector_index(
                previous,
                previous_vectors,
                CountingEmbeddingProvider(),
                max_chunks=1,
                max_characters=4000,
            )
            with self.assertRaisesRegex(ValueError, "content configuration"):
                build_vector_index(
                    new,
                    root / "new-vectors",
                    CountingEmbeddingProvider(),
                    reuse_from=previous_vectors,
                    max_chunks=2,
                    max_characters=4000,
                )


if __name__ == "__main__":
    unittest.main()
