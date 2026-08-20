from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index, search
from offline_rag.stack_exchange import import_stack_exchange
from offline_rag.verify import verify_database


USERS = """<?xml version="1.0" encoding="utf-8"?>
<users>
  <row Id="1" DisplayName="Alice Operator" />
  <row Id="2" DisplayName="Bob Builder" />
</users>
"""


POSTS = """<?xml version="1.0" encoding="utf-8"?>
<posts>
  <row Id="10" PostTypeId="1" AcceptedAnswerId="11" CreationDate="2020-01-01T00:00:00.000" Score="5" ViewCount="120" Body="&lt;p&gt;How do I make a Docker healthcheck inspect PostgreSQL?&lt;/p&gt;&lt;pre&gt;HEALTHCHECK CMD pg_isready&lt;/pre&gt;" OwnerUserId="1" LastActivityDate="2020-01-03T00:00:00.000" Title="Docker healthcheck for PostgreSQL" Tags="&lt;docker&gt;&lt;postgresql&gt;&lt;healthcheck&gt;" AnswerCount="3" ContentLicense="CC BY-SA 4.0" />
  <row Id="11" PostTypeId="2" ParentId="10" CreationDate="2020-01-02T00:00:00.000" Score="0" Body="&lt;p&gt;Use pg_isready inside the container and test its exit status.&lt;/p&gt;" OwnerUserId="2" ContentLicense="CC BY-SA 4.0" />
  <row Id="12" PostTypeId="2" ParentId="10" CreationDate="2020-01-02T01:00:00.000" Score="4" Body="&lt;p&gt;Configure start_period so initialization does not count as failure.&lt;/p&gt;" OwnerDisplayName="Deleted contributor" ContentLicense="CC BY-SA 3.0" />
  <row Id="13" PostTypeId="2" ParentId="10" CreationDate="2020-01-02T02:00:00.000" Score="-1" Body="&lt;p&gt;This low quality answer must be excluded.&lt;/p&gt;" ContentLicense="CC BY-SA 4.0" />
  <row Id="1000000001" PostTypeId="1" CreationDate="2025-07-01T00:00:00.000" Score="0" Body="&lt;p&gt;Artificial row.&lt;/p&gt;" Title="Artificial" Tags="" AnswerCount="0" />
</posts>
"""


class StackExchangeImportTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "Users.xml").write_text(USERS, encoding="utf-8")
        (source / "Posts.xml").write_text(POSTS, encoding="utf-8")
        return source

    def test_structure_retention_policy_and_bm25_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            source_before = (source / "Posts.xml").read_bytes()
            output = root / "processed"
            result = import_stack_exchange(
                source,
                output,
                corpus="devops-stackexchange",
                source_version="fixture-1",
                site_url="https://devops.stackexchange.com",
                max_chars=256,
                min_chars=20,
            )
            self.assertEqual(result["documents"], 3)
            self.assertEqual(result["accepted_answers"], 1)
            self.assertEqual(result["other_positive_answers"], 1)
            self.assertEqual(result["answers_excluded_by_policy"], 1)
            self.assertEqual(result["artificial_rows_skipped"], 1)
            self.assertEqual((source / "Posts.xml").read_bytes(), source_before)

            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            by_id = {item["document_id"]: item for item in documents}
            self.assertEqual(set(by_id), {
                "devops-stackexchange:post:10",
                "devops-stackexchange:post:11",
                "devops-stackexchange:post:12",
            })
            self.assertEqual(by_id["devops-stackexchange:post:11"]["source_url"], "https://devops.stackexchange.com/a/11")
            self.assertTrue(by_id["devops-stackexchange:post:11"]["attributes"]["accepted_answer"])
            self.assertEqual(by_id["devops-stackexchange:post:11"]["attributes"]["parent_question_id"], 10)
            self.assertEqual(by_id["devops-stackexchange:post:11"]["attributes"]["owner_display_name"], "Bob Builder")
            self.assertEqual(by_id["devops-stackexchange:post:12"]["license"], "CC BY-SA 3.0")
            self.assertTrue(any("HEALTHCHECK CMD pg_isready" in item["text"] for item in chunks))
            self.assertTrue(all(item["heading_path"][0] in {"Question", "Answer"} for item in chunks))

            manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["configuration"]["document_granularity"], "one document per retained post")
            self.assertEqual(manifest["counts"], {"documents": 3, "chunks": len(chunks)})

            database = root / "devops.sqlite3"
            build_index(output, database)
            hit = search(database, "pg_isready exit status", limit=3)[0]
            self.assertEqual(hit["document_id"], "devops-stackexchange:post:11")
            self.assertEqual(hit["source_url"], "https://devops.stackexchange.com/a/11")
            self.assertIn("devops-stackexchange", hit["citation"])
            self.assertTrue(verify_database(database, output, smoke_queries=("pg_isready",))["verified"])

    def test_existing_and_unrecognized_output_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            output = root / "processed"
            common = {
                "corpus": "devops-stackexchange",
                "source_version": "fixture-1",
                "site_url": "https://devops.stackexchange.com",
            }
            import_stack_exchange(source, output, **common)
            before = (output / "documents.jsonl").read_bytes()
            with self.assertRaises(FileExistsError):
                import_stack_exchange(source, output, **common)
            self.assertEqual((output / "documents.jsonl").read_bytes(), before)
            (output / "personal.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                import_stack_exchange(source, output, force=True, **common)
            self.assertEqual((output / "personal.txt").read_text(encoding="utf-8"), "preserve")

    def test_invalid_or_empty_inputs_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            with self.assertRaises(FileNotFoundError):
                import_stack_exchange(
                    source,
                    root / "out",
                    corpus="fixture",
                    source_version="1",
                    site_url="https://example.test",
                )


if __name__ == "__main__":
    unittest.main()
