from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import CountingFakeEmbeddingProvider, write_archive
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from offline_rag.bm25 import build_index
from offline_rag.chunk_vector_index import build_chunk_vector_index
from offline_rag.documentation import import_documentation
from offline_rag.knowledge import KnowledgeCorpus, KnowledgeRuntime
from offline_rag.knowledge_mcp_server import _provider_factories, close_knowledge_mcp_server, create_knowledge_mcp_server
from offline_rag.retrieval_runtime import CachedEmbeddingProvider
from offline_rag.vector_index import build_vector_index
from offline_rag.wikipedia_dump import extract


class KnowledgeMCPTests(unittest.TestCase):
    def test_corpus_vector_manifests_select_matching_embedding_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            models.write_text(
                json.dumps({"models": [
                    {"id": "small", "role": "embedding", "ollama_model": "same:latest", "embedding_dimensions": 256, "priority": 1},
                    {"id": "large", "role": "embedding", "ollama_model": "same:latest", "embedding_dimensions": 1024, "priority": 2},
                ]}),
                encoding="utf-8",
            )

            vectors: dict[str, Path] = {}
            for corpus, model_id, dimensions in (("one", "small", 256), ("two", "large", 1024), ("three", "small", 256)):
                path = root / corpus
                path.mkdir()
                for name in ("vectors.faiss", "metadata.sqlite3"):
                    (path / name).write_bytes(b"")
                (path / "manifest.json").write_text(json.dumps({
                    "schema_version": 1,
                    "dimensions": dimensions,
                    "provider": {
                        "provider": "ollama",
                        "model_id": model_id,
                        "runtime_model": "same:latest",
                        "dimensions": dimensions,
                        "query_instruction": None,
                    },
                    "files": {
                        "faiss": {"name": "vectors.faiss", "bytes": 0},
                        "metadata": {"name": "metadata.sqlite3", "bytes": 0},
                    },
                }), encoding="utf-8")
                vectors[corpus] = path

            factories = _provider_factories(
                vectors,
                models=models,
                model_id=None,
                ollama_url="http://127.0.0.1:11434",
                query_cache_size=8,
            )
            self.assertEqual(factories["one"]().dimensions, 256)
            self.assertEqual(factories["two"]().dimensions, 1024)
            self.assertIs(factories["one"](), factories["three"]())
            self.assertIsNot(factories["one"](), factories["two"]())
            with self.assertRaisesRegex(ValueError, "does not match"):
                _provider_factories(
                    vectors,
                    models=models,
                    model_id="small",
                    ollama_url="http://127.0.0.1:11434",
                    query_cache_size=8,
                )

    def prepare(self, root: Path) -> tuple[Path, Path]:
        wikipedia_output = root / "wikipedia-processed"
        extract(write_archive(root), wikipedia_output, "20260801", None, 3200)
        wikipedia_database = root / "wikipedia.sqlite3"
        build_index(wikipedia_output, wikipedia_database)

        source = root / "documentation-source"
        source.mkdir()
        (source / "operations.md").write_text(
            """# Spacecraft Operations

The Apollo Guidance Computer performed navigation aboard Apollo spacecraft.

## Interfaces

The guidance computer exchanged telemetry with mission systems.
""",
            encoding="utf-8",
        )
        (source / "protocol.md").write_text(
            """# Test Transport Protocol

Connection migration allows an endpoint to move to a new network path.
""",
            encoding="utf-8",
        )
        documentation_output = root / "documentation-processed"
        import_documentation(
            source,
            documentation_output,
            corpus="test-docs",
            source_version="1",
            license_name="test",
            base_url="https://example.test/docs/",
        )
        documentation_database = root / "documentation.sqlite3"
        build_index(documentation_output, documentation_database)
        return wikipedia_database, documentation_database

    def test_unified_tools_search_filter_retrieve_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            wikipedia, documentation = self.prepare(Path(directory))
            server = create_knowledge_mcp_server(
                [KnowledgeCorpus("wikipedia", wikipedia), KnowledgeCorpus("test-docs", documentation)]
            )
            try:
                tools = asyncio.run(server.list_tools())
                self.assertEqual(
                    {tool.name for tool in tools},
                    {
                        "search_knowledge",
                        "retrieve_knowledge_context",
                        "retrieve_knowledge_document",
                        "knowledge_index_status",
                    },
                )
                search = asyncio.run(
                    server.call_tool(
                        "search_knowledge",
                        {"query": "Apollo Guidance Computer", "limit": 4, "corpora": ["wikipedia", "test-docs"]},
                    )
                )
                self.assertFalse(search.is_error)
                results = search.structured_content["results"]
                self.assertEqual({item["knowledge_corpus"] for item in results}, {"wikipedia", "test-docs"})
                wikipedia_result = next(item for item in results if item["knowledge_corpus"] == "wikipedia")
                context = asyncio.run(
                    server.call_tool(
                        "retrieve_knowledge_context",
                        {
                            "corpus": "wikipedia",
                            "chunk_id": wikipedia_result["chunk_id"],
                            "before": 30,
                        },
                    )
                )
                self.assertFalse(context.is_error)
                self.assertTrue(context.structured_content["context"]["clamped"])
                self.assertEqual(context.structured_content["knowledge_corpus"], "wikipedia")

                filtered = asyncio.run(
                    server.call_tool(
                        "search_knowledge",
                        {"query": "connection migration network path", "corpora": ["test-docs"]},
                    )
                )
                self.assertEqual(filtered.structured_content["corpora_searched"], ["test-docs"])
                self.assertEqual(filtered.structured_content["results"][0]["title"], "Test Transport Protocol")

                bounded = asyncio.run(
                    server.call_tool(
                        "search_knowledge",
                        {"query": "connection migration", "corpora": ["test-docs"], "limit": 500},
                    )
                )
                self.assertEqual(bounded.structured_content["request"]["effective_limit"], 20)
                self.assertTrue(bounded.structured_content["request"]["clamped"])

                status = asyncio.run(server.call_tool("knowledge_index_status", {}))
                self.assertEqual(status.structured_content["corpus_count"], 2)
                self.assertFalse(status.structured_content["corpora"]["wikipedia"]["retrieval"]["semantic"]["loaded"])

                with self.assertRaisesRegex(Exception, "unknown corpus"):
                    asyncio.run(
                        server.call_tool("search_knowledge", {"query": "test", "corpora": ["missing"]})
                    )
            finally:
                close_knowledge_mcp_server(server)

    def test_unavailable_semantic_backend_falls_back_to_bm25(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wikipedia, _ = self.prepare(root)
            vectors = root / "vectors"
            build_vector_index(wikipedia, vectors, CountingFakeEmbeddingProvider(), batch_size=2)

            def unavailable_provider() -> CountingFakeEmbeddingProvider:
                raise RuntimeError("embedding provider is offline")

            runtime = KnowledgeRuntime(
                [
                    KnowledgeCorpus(
                        "wikipedia",
                        wikipedia,
                        vector_directory=vectors,
                        provider_factory=unavailable_provider,
                        default_retrieval="hybrid",
                    )
                ]
            )
            try:
                result = runtime.search("Apollo Guidance Computer", retrieval="default")
                self.assertEqual(result["results"][0]["document_id"], "enwiki:100")
                state = result["retrieval_by_corpus"]["wikipedia"]
                self.assertTrue(state["fallback"])
                self.assertEqual(state["used"], "bm25")
                self.assertIn("embedding provider is offline", state["fallback_reason"])
            finally:
                runtime.close()

    def test_multiple_semantic_corpora_and_automatic_routing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wikipedia, documentation = self.prepare(root)
            wikipedia_vectors = root / "wikipedia-vectors"
            documentation_vectors = root / "documentation-vectors"
            build_vector_index(wikipedia, wikipedia_vectors, CountingFakeEmbeddingProvider(), batch_size=2)
            build_chunk_vector_index(
                documentation,
                documentation_vectors,
                CountingFakeEmbeddingProvider(),
                batch_size=2,
            )
            serving_provider = CountingFakeEmbeddingProvider()
            shared_provider = CachedEmbeddingProvider(serving_provider, maximum_queries=8)
            runtime = KnowledgeRuntime(
                [
                    KnowledgeCorpus(
                        "wikipedia",
                        wikipedia,
                        vector_directory=wikipedia_vectors,
                        provider_factory=lambda: shared_provider,
                        default_retrieval="hybrid",
                    ),
                    KnowledgeCorpus(
                        "test-docs",
                        documentation,
                        vector_directory=documentation_vectors,
                        provider_factory=lambda: shared_provider,
                        default_retrieval="hybrid",
                    ),
                ]
            )
            try:
                conceptual = runtime.search(
                    "move a connection to a new network path",
                    corpus_ids=["test-docs"],
                    retrieval="auto",
                )
                self.assertEqual(conceptual["retrieval_by_corpus"]["test-docs"]["used"], "hybrid")
                self.assertEqual(conceptual["results"][0]["title"], "Test Transport Protocol")
                self.assertEqual(conceptual["reranker"], "deterministic-evidence-v2")

                runtime.search("lunar navigation", retrieval="hybrid")
                self.assertEqual(serving_provider.query_calls, 2)
                self.assertEqual(shared_provider.status()["hits"], 1)

                exact = runtime.search(
                    "openat2 RESOLVE_BENEATH",
                    corpus_ids=["test-docs"],
                    retrieval="auto",
                )
                self.assertEqual(exact["retrieval_by_corpus"]["test-docs"]["used"], "bm25")
                self.assertIn("technical identifiers", exact["retrieval_by_corpus"]["test-docs"]["route_reason"])
                self.assertIsNone(exact["reranker"])
                status = runtime.status()
                self.assertEqual(status["corpora"]["wikipedia"]["retrieval"]["available_modes"], ["bm25", "semantic", "hybrid"])
                self.assertEqual(status["corpora"]["test-docs"]["retrieval"]["available_modes"], ["bm25", "semantic", "hybrid"])
            finally:
                runtime.close()

    def test_stdio_transport_round_trip_with_multiple_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            wikipedia, documentation = self.prepare(Path(directory))

            async def exercise() -> None:
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "offline_rag.knowledge_mcp_server",
                        "--index",
                        f"wikipedia={wikipedia}",
                        "--index",
                        f"test-docs={documentation}",
                    ],
                    env=environment,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertIn("search_knowledge", {tool.name for tool in tools.tools})
                        result = await session.call_tool(
                            "search_knowledge",
                            {"query": "connection migration", "corpora": ["test-docs"], "limit": 1},
                        )
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.structured_content["results"][0]["knowledge_corpus"], "test-docs")

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
