from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.records import (
    chunk_records_to_common,
    common_chunk_from_record,
    common_document_from_record,
    make_content_id,
    wikipedia_chunks_to_common,
    wikipedia_document_to_common,
)


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

    def test_native_common_records_are_validated(self):
        document = common_document_from_record(
            {
                "schema_version": 1,
                "document_id": "python:library/pathlib",
                "corpus": "python-docs",
                "title": "pathlib",
                "source_url": "https://docs.python.org/3/library/pathlib.html",
                "source_version": "3.14.7",
                "source_timestamp": None,
                "license": "PSF-2.0",
                "content_hash": make_content_id("Paths"),
                "attributes": {"relative_path": "library/pathlib.html"},
            }
        )
        chunk_record = {
            "schema_version": 1,
            "chunk_instance_id": "instance-1",
            "content_id": make_content_id("Paths are objects."),
            "document_id": document.document_id,
            "parent_chunk_id": None,
            "ordinal": 0,
            "heading_path": ["Object-oriented filesystem paths"],
            "text": "Paths are objects.",
            "character_count": len("Paths are objects."),
            "token_count": None,
            "previous_chunk_id": None,
            "next_chunk_id": None,
            "attributes": {},
        }
        chunk = common_chunk_from_record(chunk_record)
        streamed = list(chunk_records_to_common(iter([chunk_record])))
        self.assertEqual(document.source_version, "3.14.7")
        self.assertEqual(chunk, streamed[0])
        invalid = dict(chunk_record, character_count=999)
        with self.assertRaisesRegex(ValueError, "character_count"):
            common_chunk_from_record(invalid)


if __name__ == "__main__":
    unittest.main()
