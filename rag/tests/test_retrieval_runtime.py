from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import CountingFakeEmbeddingProvider, write_archive
from offline_rag.bm25 import build_index
from offline_rag.retrieval_runtime import RetrievalRuntime, RetrievalUnavailableError
from offline_rag.vector_index import build_vector_index
from offline_rag.wikipedia_dump import extract


class FailingQueryProvider(CountingFakeEmbeddingProvider):
    def embed_query(self, query: str):
        raise RuntimeError("embedding endpoint unavailable")


class RetrievalRuntimeTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        build_index(processed, database)
        vectors = root / "vectors"
        build_vector_index(database, vectors, CountingFakeEmbeddingProvider(), batch_size=2)
        return database, vectors

    def test_lazy_load_hybrid_search_and_bounded_query_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            database, vectors = self.prepare(Path(directory))
            serving_provider = CountingFakeEmbeddingProvider()
            factory_calls = 0

            def factory() -> CountingFakeEmbeddingProvider:
                nonlocal factory_calls
                factory_calls += 1
                return serving_provider

            runtime = RetrievalRuntime(
                database,
                vector_directory=vectors,
                provider_factory=factory,
                default_mode="hybrid",
                query_cache_size=2,
            )
            try:
                status = runtime.status()
                self.assertFalse(status["semantic"]["loaded"])
                self.assertEqual(factory_calls, 0)

                semantic = runtime.search(
                    "lunar navigation",
                    limit=2,
                    query_mode="and",
                    retrieval_mode="semantic",
                )
                self.assertEqual(semantic["results"][0]["document_id"], "enwiki:100")
                self.assertEqual(semantic["retrieval_mode"], "semantic")
                self.assertEqual(factory_calls, 1)
                self.assertEqual(serving_provider.query_calls, 1)

                hybrid = runtime.search(
                    "lunar navigation",
                    limit=2,
                    query_mode="and",
                    retrieval_mode="hybrid",
                )
                self.assertEqual(hybrid["results"][0]["document_id"], "enwiki:100")
                self.assertEqual(hybrid["retrieval_mode"], "hybrid")
                self.assertEqual(serving_provider.query_calls, 1)
                cache = runtime.status()["semantic"]["query_cache"]
                self.assertEqual(cache["entries"], 1)
                self.assertEqual(cache["hits"], 1)
                self.assertEqual(cache["misses"], 1)
            finally:
                runtime.close()

    def test_bm25_stays_ready_without_semantic_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            database, _ = self.prepare(Path(directory))
            runtime = RetrievalRuntime(database)
            try:
                result = runtime.search("Apollo Guidance Computer", limit=2, query_mode="and")
                self.assertEqual(result["retrieval_mode"], "bm25")
                self.assertEqual(runtime.status()["available_modes"], ["bm25"])
                with self.assertRaisesRegex(RetrievalUnavailableError, "no verified published generation"):
                    runtime.search(
                        "lunar navigation",
                        limit=2,
                        query_mode="and",
                        retrieval_mode="semantic",
                    )
            finally:
                runtime.close()

    def test_vector_search_is_safe_across_request_threads(self):
        with tempfile.TemporaryDirectory() as directory:
            database, vectors = self.prepare(Path(directory))
            runtime = RetrievalRuntime(
                database,
                vector_directory=vectors,
                provider_factory=CountingFakeEmbeddingProvider,
                default_mode="semantic",
            )
            try:
                def search(_: int) -> str:
                    result = runtime.search(
                        "lunar navigation",
                        limit=2,
                        query_mode="and",
                        retrieval_mode="semantic",
                    )
                    return str(result["results"][0]["document_id"])

                with ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(search, range(12)))
                self.assertEqual(results, ["enwiki:100"] * 12)
            finally:
                runtime.close()

    def test_query_provider_failure_is_reported_as_optional_backend_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            database, vectors = self.prepare(Path(directory))
            runtime = RetrievalRuntime(
                database,
                vector_directory=vectors,
                provider_factory=FailingQueryProvider,
                default_mode="semantic",
            )
            try:
                with self.assertRaisesRegex(RetrievalUnavailableError, "embedding endpoint unavailable"):
                    runtime.search("lunar navigation", limit=2, query_mode="and")
                self.assertEqual(
                    runtime.status()["semantic"]["last_query_error"],
                    "embedding endpoint unavailable",
                )
                lexical = runtime.search(
                    "Apollo Guidance Computer",
                    limit=2,
                    query_mode="and",
                    retrieval_mode="bm25",
                )
                self.assertEqual(lexical["results"][0]["document_id"], "enwiki:100")
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
