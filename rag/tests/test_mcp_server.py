from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_archive
from offline_rag.bm25 import build_index
from offline_rag.mcp_server import create_mcp_server
from offline_rag.wikipedia_dump import extract
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class MCPServerTests(unittest.TestCase):
    def prepare(self, root: Path) -> Path:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        build_index(processed, database)
        return database

    def test_tools_list_search_and_retrieve(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_mcp_server(self.prepare(Path(directory)))
            tools = asyncio.run(server.list_tools())
            self.assertEqual(
                {tool.name for tool in tools},
                {"search_wikipedia", "retrieve_wikipedia_document", "wikipedia_index_status"},
            )

            result = asyncio.run(
                server.call_tool(
                    "search_wikipedia",
                    {"query": "What was the Apollo Guidance Computer?", "limit": 3, "mode": "and"},
                )
            )
            self.assertIsNotNone(result.structured_content)
            self.assertEqual(result.structured_content["results"][0]["document_id"], "enwiki:100")

            document = asyncio.run(
                server.call_tool(
                    "retrieve_wikipedia_document",
                    {"document_id": "enwiki:100", "chunk_limit": 2},
                )
            )
            self.assertEqual(document.structured_content["document"]["title"], "Apollo Guidance Computer")

    def test_stdio_transport_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            database = self.prepare(Path(directory))

            async def exercise() -> None:
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "offline_rag.mcp_server",
                        "--database",
                        str(database),
                    ],
                    env=environment,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertIn("search_wikipedia", {tool.name for tool in tools.tools})
                        result = await session.call_tool(
                            "search_wikipedia",
                            {"query": "Apollo Guidance Computer", "limit": 1, "mode": "and"},
                        )
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.structured_content["results"][0]["document_id"], "enwiki:100")

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
