from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.records import make_content_id, wikipedia_chunks_to_common, wikipedia_document_to_common


class RecordTests(unittest.TestCase):
    def test_wikipedia_conversion_separates_content_and_instance_identity(self):
        document = wikipedia_document_to_common(
            {
                "document_id": "enwiki:1",
                "source": "wikipedia-en",
                "dump_date": "20260801",
                "article_id": 1,
                "revision_id": 2,
                "revision_timestamp": "2026-08-01T00:00:00Z",
                "title": "Example",
                "source_url": "https://example.invalid",
                "redirect_target": None,
            }
        )
        items = [
            {
                "chunk_id": "instance-a",
                "document_id": "enwiki:1",
                "heading_path": [],
                "text": "Same normalized text",
                "content_hash": make_content_id("Same normalized text").split(":", 1)[1],
                "section_index": 0,
                "chunk_index": 0,
            },
            {
                "chunk_id": "instance-b",
                "document_id": "enwiki:1",
                "heading_path": ["Section"],
                "text": "Same normalized text",
                "content_hash": make_content_id("Same normalized text").split(":", 1)[1],
                "section_index": 1,
                "chunk_index": 0,
            },
        ]
        chunks = list(wikipedia_chunks_to_common(items))
        self.assertEqual(document.corpus, "wikipedia-en")
        self.assertEqual(document.attributes["article_id"], 1)
        self.assertEqual(chunks[0].content_id, chunks[1].content_id)
        self.assertNotEqual(chunks[0].chunk_instance_id, chunks[1].chunk_instance_id)
        self.assertEqual(chunks[0].next_chunk_id, "instance-b")
        self.assertEqual(chunks[1].previous_chunk_id, "instance-a")
        self.assertEqual(chunks[1].ordinal, 1)


if __name__ == "__main__":
    unittest.main()

