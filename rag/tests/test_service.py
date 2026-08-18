from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import CountingFakeEmbeddingProvider, write_archive
from offline_rag.bm25 import build_index
from offline_rag.retrieval import index_status, retrieve_chunk_context, retrieve_document
from offline_rag.service import create_server
from offline_rag.vector_index import build_vector_index
from offline_rag.wikipedia_dump import extract


class ServiceTests(unittest.TestCase):
    def prepare(self, root: Path) -> Path:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        build_index(processed, database)
        return database

    def test_status_and_document_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            database = self.prepare(Path(directory))
            status = index_status(database)
            self.assertTrue(status["ready"])
            self.assertEqual(status["document_count"], 3)
            result = retrieve_document(database, "enwiki:100", chunk_limit=1)
            self.assertEqual(result["document"]["title"], "Apollo Guidance Computer")
            self.assertEqual(result["pagination"]["returned"], 1)
            self.assertIn("Wikipedia — Apollo Guidance Computer", result["chunks"][0]["citation"])
            context = retrieve_chunk_context(database, result["chunks"][0]["chunk_id"], before=0, after=1)
            self.assertEqual(context["context"]["anchor_chunk_id"], result["chunks"][0]["chunk_id"])
            self.assertLessEqual(context["pagination"]["returned"], 2)
            with self.assertRaises(KeyError):
                retrieve_document(database, "enwiki:missing")
            with self.assertRaises(KeyError):
                retrieve_chunk_context(database, "missing-chunk")

    def test_http_health_search_document_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = self.prepare(Path(directory))
            server = create_server(database, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/health", timeout=5) as response:
                    health = json.load(response)
                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["index"]["document_count"], 3)
                self.assertEqual(health["retrieval"]["available_modes"], ["bm25"])

                request = Request(
                    f"{base}/v1/search",
                    data=json.dumps(
                        {"query": "What was the Apollo Guidance Computer?", "limit": 3, "mode": "and"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    search_result = json.load(response)
                self.assertEqual(search_result["results"][0]["document_id"], "enwiki:100")
                self.assertEqual(search_result["results"][0]["ranking_reason"], "exact_title")
                self.assertEqual(search_result["ranking_unit"], "document")
                document_ids = [item["document_id"] for item in search_result["results"]]
                self.assertEqual(len(document_ids), len(set(document_ids)))

                relaxed_request = Request(
                    f"{base}/v1/search",
                    data=json.dumps(
                        {"query": "Apollo Guidance Computer IBM", "limit": 3, "mode": "and"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(relaxed_request, timeout=5) as response:
                    relaxed = json.load(response)
                self.assertTrue(relaxed["query_relaxed"])
                self.assertEqual(relaxed["results"][0]["document_id"], "enwiki:100")

                document_url = f"{base}/v1/documents/{quote('enwiki:100', safe='')}?limit=2"
                with urlopen(document_url, timeout=5) as response:
                    document = json.load(response)
                self.assertEqual(document["document"]["title"], "Apollo Guidance Computer")
                self.assertGreaterEqual(document["pagination"]["total_chunks"], 1)

                with self.assertRaises(HTTPError) as context:
                    urlopen(f"{base}/v1/search?q=&limit=3", timeout=5)
                self.assertEqual(context.exception.code, 400)
                context.exception.close()

                unavailable_request = Request(
                    f"{base}/v1/search",
                    data=json.dumps(
                        {"query": "lunar navigation", "retrieval_mode": "semantic", "limit": 2}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as unavailable:
                    urlopen(unavailable_request, timeout=5)
                self.assertEqual(unavailable.exception.code, 503)
                unavailable.exception.close()

                with urlopen(base, timeout=5) as response:
                    html = response.read().decode()
                self.assertIn("Offline Wikipedia", html)
                self.assertIn("/v1/search", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_semantic_and_hybrid_modes_are_lazy_and_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = self.prepare(root)
            vectors = root / "vectors"
            build_vector_index(database, vectors, CountingFakeEmbeddingProvider(), batch_size=2)
            provider = CountingFakeEmbeddingProvider()
            server = create_server(
                database,
                port=0,
                vector_directory=vectors,
                provider_factory=lambda: provider,
                default_retrieval="hybrid",
                query_cache_size=4,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/health", timeout=5) as response:
                    health = json.load(response)
                self.assertEqual(health["retrieval"]["available_modes"], ["bm25", "semantic", "hybrid"])
                self.assertFalse(health["retrieval"]["semantic"]["loaded"])
                self.assertEqual(provider.query_calls, 0)

                for retrieval_mode in ("semantic", "hybrid"):
                    request = Request(
                        f"{base}/v1/search",
                        data=json.dumps(
                            {
                                "query": "lunar navigation",
                                "limit": 2,
                                "mode": "and",
                                "retrieval_mode": retrieval_mode,
                            }
                        ).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request, timeout=5) as response:
                        result = json.load(response)
                    self.assertEqual(result["retrieval_mode"], retrieval_mode)
                    self.assertEqual(result["results"][0]["document_id"], "enwiki:100")

                self.assertEqual(provider.query_calls, 1)
                with urlopen(f"{base}/health", timeout=5) as response:
                    loaded = json.load(response)
                self.assertTrue(loaded["retrieval"]["semantic"]["loaded"])
                self.assertEqual(loaded["retrieval"]["semantic"]["query_cache"]["hits"], 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
