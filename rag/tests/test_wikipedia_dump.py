from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_archive
from offline_rag.wikipedia_dump import (
    ExtractionInterrupted,
    chunk_section,
    extract,
    iter_sections,
    main,
    page_records,
)


class StopAfterOneDocument:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls >= 2


class WikipediaDumpTests(unittest.TestCase):
    def test_complete_extraction_filters_namespaces_and_preserves_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            stats = extract(write_archive(root), output, "20260801", None, 3200)
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text().splitlines()]
            checkpoint = json.loads((output / "checkpoint.json").read_text())
            self.assertEqual(stats["stop_reason"], "archive_complete")
            self.assertTrue(stats["completed"])
            self.assertEqual(stats["documents"], 3)
            self.assertNotIn("Talk:Apollo Guidance Computer", [item["title"] for item in documents])
            self.assertEqual(documents[1]["redirect_target"], "Apollo Guidance Computer")
            guidance = next(item for item in chunks if "guidance programs controlled" in item["text"])
            self.assertEqual(guidance["heading_path"], ["Software", "Guidance programs"])
            self.assertNotIn("thumb", chunks[0]["text"])
            self.assertTrue(checkpoint["completed"])
            self.assertEqual(checkpoint["stop_reason"], "archive_complete")

    def test_limited_extraction_is_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            stats = extract(write_archive(root), output, "20260801", 1, 3200)
            checkpoint = json.loads((output / "checkpoint.json").read_text())
            self.assertEqual(stats["documents"], 1)
            self.assertFalse(stats["completed"])
            self.assertEqual(stats["stop_reason"], "article_limit")
            self.assertFalse(checkpoint["completed"])

    def test_resume_at_reached_limit_adds_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            extract(archive, output, "20260801", 1, 3200)
            before = ((output / "documents.jsonl").read_bytes(), (output / "chunks.jsonl").read_bytes())
            stats = extract(archive, output, "20260801", 1, 3200, resume=True)
            after = ((output / "documents.jsonl").read_bytes(), (output / "chunks.jsonl").read_bytes())
            self.assertEqual(before, after)
            self.assertEqual(stats["documents"], 1)
            self.assertEqual(stats["stop_reason"], "article_limit")

    def test_resume_version_one_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            extract(archive, output, "20260801", 1, 3200)
            current = json.loads((output / "checkpoint.json").read_text())
            legacy = {
                "schema_version": 1,
                "archive": str(archive.resolve()),
                "archive_size": archive.stat().st_size,
                "dump_date": "20260801",
                "max_chunk_characters": 3200,
                "documents": current["documents"],
                "redirects": current["redirects"],
                "chunks": current["chunks"],
                "documents_offset": current["documents_offset"],
                "chunks_offset": current["chunks_offset"],
                "completed": False,
            }
            (output / "checkpoint.json").write_text(json.dumps(legacy))
            stats = extract(archive, output, "20260801", None, 3200, resume=True)
            self.assertEqual(stats["documents"], 3)
            self.assertEqual(stats["stop_reason"], "archive_complete")

    def test_graceful_interruption_is_consistent_and_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            with self.assertRaises(ExtractionInterrupted):
                extract(
                    archive,
                    output,
                    "20260801",
                    None,
                    3200,
                    checkpoint_interval=10,
                    stop_requested=StopAfterOneDocument(),
                )
            checkpoint = json.loads((output / "checkpoint.json").read_text())
            stats = json.loads((output / "extraction-stats.json").read_text())
            documents = (output / "documents.jsonl").read_text().splitlines()
            chunks = (output / "chunks.jsonl").read_text().splitlines()
            self.assertEqual(checkpoint["documents"], 1)
            self.assertEqual(len(documents), 1)
            self.assertEqual(len(chunks), checkpoint["chunks"])
            self.assertEqual(stats["stop_reason"], "interrupted")
            resumed = extract(archive, output, "20260801", None, 3200, resume=True)
            self.assertEqual(resumed["documents"], 3)
            self.assertTrue(resumed["completed"])

    def test_checkpoint_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            extract(archive, output, "20260801", 1, 3200)
            archive.write_bytes(archive.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "identity bytes mismatch"):
                extract(archive, output, "20260801", None, 3200, resume=True)

    def test_unexpected_failure_rolls_back_and_is_distinguished(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            calls = 0

            def fail_on_second_page(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("synthetic parser failure")
                return page_records(*args, **kwargs)

            with patch("offline_rag.wikipedia_dump.page_records", side_effect=fail_on_second_page):
                with self.assertRaisesRegex(RuntimeError, "synthetic parser failure"):
                    extract(archive, output, "20260801", None, 3200, checkpoint_interval=1)
            checkpoint = json.loads((output / "checkpoint.json").read_text())
            stats = json.loads((output / "extraction-stats.json").read_text())
            self.assertEqual(checkpoint["documents"], 1)
            self.assertEqual(len((output / "documents.jsonl").read_text().splitlines()), 1)
            self.assertEqual(checkpoint["stop_reason"], "failed")
            self.assertEqual(stats["stop_reason"], "failed")
            self.assertEqual(stats["error"]["type"], "RuntimeError")
            self.assertFalse((output / "checkpoint.tmp").exists())
            self.assertFalse((output / "extraction-stats.tmp").exists())

    def test_existing_output_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            output = root / "output"
            output.mkdir()
            (output / "documents.jsonl").write_text("do not overwrite")
            (output / "unrelated.txt").write_text("preserve me")
            with self.assertRaises(FileExistsError):
                extract(archive, output, "20260801", None, 3200)
            stats = extract(archive, output, "20260801", None, 3200, force=True)
            self.assertTrue(stats["completed"])
            self.assertEqual((output / "unrelated.txt").read_text(), "preserve me")

    def test_argument_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root)
            for kwargs in (
                {"max_chars": 0},
                {"max_articles": 0},
                {"checkpoint_interval": 0},
                {"resume": True, "force": True},
            ):
                values = {"max_articles": None, "max_chars": 3200, **kwargs}
                with self.assertRaises(ValueError):
                    extract(archive, root / "output", "20260801", **values)
            with self.assertRaises(FileNotFoundError):
                extract(root / "missing.bz2", root / "output", "20260801", None, 3200)

    def test_chunking_preserves_oversized_and_short_content(self):
        oversized = "x" * 25
        chunks = chunk_section(oversized, max_chars=10, min_chars=6)
        self.assertEqual("".join(chunks), oversized)
        self.assertEqual([len(value) for value in chunks], [10, 10, 5])
        self.assertEqual(chunk_section("brief", max_chars=10, min_chars=6), ["brief"])

    def test_nested_heading_iterator(self):
        sections = list(iter_sections("Lead text.\n\n== One ==\nFirst.\n\n=== Two ===\nSecond."))
        self.assertEqual([path for path, _ in sections], [[], ["One"], ["One", "Two"]])

    def test_interrupted_cli_status_is_130(self):
        with patch("offline_rag.wikipedia_dump.extract", side_effect=ExtractionInterrupted("stopped")):
            status = main(["--archive", "unused", "--output", "unused", "--dump-date", "20260801"])
        self.assertEqual(status, 130)


if __name__ == "__main__":
    unittest.main()

