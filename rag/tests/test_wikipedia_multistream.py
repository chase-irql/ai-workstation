from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_multistream_archive
from offline_rag.bm25 import build_index, read_jsonl, search
from offline_rag.wikipedia_multistream import (
    ParallelExtractionInterrupted,
    extract_multistream,
    iter_stream_blocks,
)


class WikipediaMultistreamTests(unittest.TestCase):
    def test_blocks_parallel_extract_resume_and_direct_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, index = write_multistream_archive(root)
            blocks = list(iter_stream_blocks(index, archive.stat().st_size))
            self.assertEqual([block.pages for block in blocks], [2, 2])

            output = root / "processed"
            limited = extract_multistream(
                archive,
                index,
                output,
                "20260801",
                workers=2,
                batch_blocks=1,
                max_parts=1,
            )
            self.assertFalse(limited["completed"])
            self.assertEqual(limited["stop_reason"], "part_limit")
            self.assertEqual(limited["totals"]["documents"], 2)

            complete = extract_multistream(
                archive,
                index,
                output,
                "20260801",
                workers=2,
                batch_blocks=1,
                resume=True,
            )
            self.assertTrue(complete["completed"])
            self.assertEqual(complete["stop_reason"], "archive_complete")
            self.assertEqual(complete["totals"]["documents"], 3)
            self.assertEqual(complete["totals"]["redirects"], 1)

            manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
            documents = [
                item
                for part in manifest["parts"]
                for item in read_jsonl(output / part["documents"])
            ]
            self.assertEqual([item["document_id"] for item in documents], ["enwiki:100", "enwiki:101", "enwiki:102"])

            database = root / "parallel.sqlite3"
            result = build_index(output, database)
            self.assertEqual(result["documents"], 3)
            self.assertEqual(search(database, "reciprocal rank fusion", limit=1)[0]["document_id"], "enwiki:102")

    def test_pre_requested_interrupt_is_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, index = write_multistream_archive(root)
            shutdown = threading.Event()
            shutdown.set()
            with self.assertRaises(ParallelExtractionInterrupted):
                extract_multistream(
                    archive,
                    index,
                    root / "processed",
                    "20260801",
                    workers=1,
                    batch_blocks=1,
                    stop_requested=shutdown,
                )
            state = json.loads((root / "processed" / "extraction-stats.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stop_reason"], "interrupted")
            self.assertEqual(state["parts"], 0)


if __name__ == "__main__":
    unittest.main()
