from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import CountingFakeEmbeddingProvider
from offline_rag.bm25 import build_index
from offline_rag.chunk_vector_index import (
    ChunkVectorIndex,
    build_chunk_vector_index,
    iter_chunk_embedding_records,
    semantic_search,
    verify_chunk_vector_index,
)
from offline_rag.documentation import import_documentation


class FailAfterOneProvider(CountingFakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]):
        if self.document_calls >= 1:
            raise RuntimeError("intentional chunk interruption")
        return super().embed_documents(texts)


class AlwaysFailProvider(CountingFakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]):
        raise RuntimeError("intentional replacement failure")


class ChunkVectorIndexTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        (source / "apollo.md").write_text(
            """# Apollo Systems

The launch vehicle used several independent computing systems and radio links.

## Guidance Computer

The Apollo Guidance Computer used rope memory and performed lunar navigation.

## Interfaces

Telemetry connected the guidance computer to mission systems and displays.
""",
            encoding="utf-8",
        )
        (source / "ranking.md").write_text(
            """# Search Ranking

Lexical search handles exact identifiers and quoted terms.

## Fusion

Reciprocal rank fusion combines independent lexical and semantic rankings.
""",
            encoding="utf-8",
        )
        processed = root / "processed"
        import_documentation(
            source,
            processed,
            corpus="test-docs",
            source_version="1",
            license_name="test",
            base_url="https://example.test/docs/",
            max_chars=160,
            min_chars=0,
        )
        database = root / "index.sqlite3"
        build_index(processed, database)
        return database, root / "vectors"

    def test_stream_includes_deep_sections_and_stable_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            database, _ = self.prepare(Path(directory))
            records = list(iter_chunk_embedding_records(database))
            self.assertGreaterEqual(len(records), 4)
            deep = next(record for record in records if "rope memory" in record.text)
            self.assertIn("Title: Apollo Systems", deep.embedding_text)
            self.assertIn("Section: Apollo Systems > Guidance Computer", deep.embedding_text)
            resumed = list(
                iter_chunk_embedding_records(database, start_after_chunk_id=records[0].chunk_instance_id)
            )
            self.assertEqual([item.chunk_instance_id for item in resumed], [item.chunk_instance_id for item in records[1:]])

    def test_build_search_verify_resume_reuse_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, destination = self.prepare(root)
            provider = CountingFakeEmbeddingProvider()
            manifest = build_chunk_vector_index(database, destination, provider, batch_size=2)
            self.assertEqual(manifest["representation"], "title-heading-chunk-v1")
            self.assertEqual(manifest["chunk_count"], 5)
            self.assertTrue(verify_chunk_vector_index(destination, database=database)["source_verified"])
            with ChunkVectorIndex(destination, database) as index:
                results = semantic_search(index, provider, "lunar rope memory", limit=2)
            result = next(item for item in results if item["title"] == "Apollo Systems")
            self.assertIn("https://example.test/docs/apollo.md", result["citation"])

            before = (destination / "manifest.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "replacement failure"):
                build_chunk_vector_index(
                    database,
                    destination,
                    AlwaysFailProvider(),
                    overwrite=True,
                    batch_size=2,
                )
            self.assertEqual((destination / "manifest.json").read_bytes(), before)
            state = json.loads((destination / ".chunk-build-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["completed_chunks"], 0)
            build_chunk_vector_index(
                database,
                destination,
                CountingFakeEmbeddingProvider(),
                restart=True,
                overwrite=True,
                reuse_from=destination,
                batch_size=2,
            )
            reused = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))["reuse"]
            self.assertEqual(reused["chunks_reused"], 5)
            self.assertEqual(reused["chunks_embedded"], 0)

    def test_interrupted_build_resumes_from_common_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            database, destination = self.prepare(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "chunk interruption"):
                build_chunk_vector_index(
                    database,
                    destination,
                    FailAfterOneProvider(),
                    batch_size=1,
                    embedding_workers=1,
                    checkpoint_interval=1,
                )
            state = json.loads((destination / ".chunk-build-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["completed_chunks"], 1)
            result = build_chunk_vector_index(
                database,
                destination,
                CountingFakeEmbeddingProvider(),
                resume=True,
                batch_size=1,
                embedding_workers=1,
                checkpoint_interval=1,
            )
            self.assertEqual(result["chunk_count"], 5)
            self.assertFalse((destination / ".chunk-build-state.json").exists())


if __name__ == "__main__":
    unittest.main()
