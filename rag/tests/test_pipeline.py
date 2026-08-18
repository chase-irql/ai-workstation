import bz2
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index, search
from offline_rag.wikipedia_dump import extract


FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page><title>Apollo Guidance Computer</title><ns>0</ns><id>100</id>
    <revision><id>200</id><timestamp>2026-08-01T00:00:00Z</timestamp>
      <text xml:space="preserve">The '''Apollo Guidance Computer''' was a digital computer. [[File:AGC.jpg|thumb|Computer photograph]]

== Software ==
Its software used rope memory and supported the Apollo missions.</text>
    </revision>
  </page>
  <page><title>AGC</title><ns>0</ns><id>101</id><redirect title="Apollo Guidance Computer" />
    <revision><id>201</id><timestamp>2026-08-01T00:00:00Z</timestamp><text>#REDIRECT</text></revision>
  </page>
</mediawiki>"""


class PipelineTests(unittest.TestCase):
    def test_extract_index_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.xml.bz2"
            archive.write_bytes(bz2.compress(FIXTURE.encode("utf-8")))
            output = root / "processed"
            stats = extract(archive, output, "20260801", max_articles=None, max_chars=3200)
            self.assertEqual(stats["documents"], 2)
            self.assertEqual(stats["redirects"], 1)
            self.assertEqual(stats["chunks"], 2)

            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(chunks[1]["heading_path"], ["Software"])
            self.assertIn("rope memory", chunks[1]["text"])
            self.assertNotIn("thumb", chunks[0]["text"])

            database = root / "wikipedia.sqlite3"
            index_stats = build_index(output, database)
            self.assertEqual(index_stats["documents"], 2)
            results = search(database, "rope memory", limit=3)
            self.assertEqual(results[0]["title"], "Apollo Guidance Computer")
            self.assertIn("Wikipedia — Apollo Guidance Computer § Software", results[0]["citation"])

    def test_extraction_can_resume_from_a_durable_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.xml.bz2"
            archive.write_bytes(bz2.compress(FIXTURE.encode("utf-8")))
            output = root / "processed"

            initial = extract(archive, output, "20260801", max_articles=1, max_chars=3200)
            resumed = extract(archive, output, "20260801", max_articles=None, max_chars=3200, resume=True)

            documents = (output / "documents.jsonl").read_text(encoding="utf-8").splitlines()
            chunks = (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(initial["documents"], 1)
            self.assertEqual(resumed["resumed_from_documents"], 1)
            self.assertEqual(resumed["documents"], 2)
            self.assertEqual(len(documents), 2)
            self.assertEqual(len(chunks), 2)
            self.assertTrue(checkpoint["completed"])


if __name__ == "__main__":
    unittest.main()
