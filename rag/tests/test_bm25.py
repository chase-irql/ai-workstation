from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_archive
from offline_rag.bm25 import build_index, plan_query, read_index_metadata, search
from offline_rag.retrieval import search_documents
from offline_rag.verify import verify_database
from offline_rag.wikipedia_dump import extract


class BM25Tests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        return processed, database

    def test_build_validates_metadata_foreign_keys_and_contentless_fts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            stats = build_index(processed, database)
            metadata = read_index_metadata(database)
            self.assertEqual(stats["documents"], 3)
            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(metadata["document_count"], 3)
            self.assertEqual(metadata["source_corpora"], ["wikipedia-en"])
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(connection.execute("SELECT count(*) FROM chunks").fetchone()[0], metadata["chunk_count"])
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0], metadata["chunk_count"]
                )
                # A contentless FTS table retains the token index, not another copy of the source text.
                self.assertIsNone(connection.execute("SELECT text FROM chunks_fts LIMIT 1").fetchone()[0])
            finally:
                connection.close()

    def test_existing_database_requires_authorized_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            database.write_bytes(b"previous database")
            before = database.read_bytes()
            with self.assertRaises(FileExistsError):
                build_index(processed, database)
            self.assertEqual(database.read_bytes(), before)
            build_index(processed, database, overwrite=True)
            self.assertEqual(read_index_metadata(database)["schema_version"], 2)

    def test_failed_build_preserves_previous_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            before = database.read_bytes()
            with (processed / "chunks.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("{malformed json}\n")
            with self.assertRaises(ValueError):
                build_index(processed, database, overwrite=True)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual(read_index_metadata(database)["schema_version"], 2)

    def test_replacement_refuses_existing_sqlite_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            database.write_bytes(b"previous database")
            sidecar = Path(f"{database}-wal")
            sidecar.write_bytes(b"uncheckpointed state")
            with self.assertRaisesRegex(RuntimeError, "sidecars exist"):
                build_index(processed, database, overwrite=True)
            self.assertEqual(database.read_bytes(), b"previous database")
            self.assertEqual(sidecar.read_bytes(), b"uncheckpointed state")

    def test_ranking_citations_and_result_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            results = search(database, "rope memory", limit=5)
            self.assertEqual(results[0]["document_id"], "enwiki:100")
            self.assertIn("Apollo Guidance Computer § Software", results[0]["citation"])
            required = {
                "raw_score",
                "document_id",
                "chunk_id",
                "title",
                "heading_path",
                "revision_timestamp",
                "source_url",
                "citation",
                "section_index",
                "chunk_index",
            }
            self.assertTrue(required.issubset(results[0]))

    def test_query_modes_and_technical_normalization(self):
        and_plan = plan_query("Apollo guidance", "and")
        or_plan = plan_query("Apollo guidance", "or")
        phrase_plan = plan_query("Apollo guidance", "phrase")
        self.assertIn(" AND ", and_plan.fts_expression)
        self.assertIn(" OR ", or_plan.fts_expression)
        self.assertEqual(phrase_plan.fts_expression, '"apollo guidance"')
        self.assertEqual(plan_query("C++", "and").normalized_terms, ("cpp",))
        self.assertEqual(plan_query("C# .NET 8", "and").normalized_terms, ("csharp", "dotnet", "8"))
        scoped = plan_query("std::vector C++", "and")
        self.assertEqual(scoped.normalized_terms[-1], "cpp")
        self.assertTrue(scoped.normalized_terms[0].startswith("scope"))
        underscored = plan_query("foo_bar", "and")
        self.assertTrue(underscored.normalized_terms[0].startswith("ident"))
        question = plan_query("What was the Apollo Guidance Computer?", "and")
        self.assertEqual(question.normalized_terms, ("apollo", "guidance", "computer"))
        self.assertEqual(
            plan_query("What was Apollo", "phrase").normalized_terms,
            ("what", "was", "apollo"),
        )

    def test_natural_question_promotes_exact_title(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            results = search(database, "What was the Apollo Guidance Computer?", limit=5)
            self.assertEqual(results[0]["document_id"], "enwiki:100")
            self.assertEqual(results[0]["ranking_reason"], "exact_title")
            self.assertEqual(results[0]["ordinal"], 0)

    def test_document_search_relaxes_one_bad_term_and_returns_lead(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            response = search_documents(database, "Apollo Guidance Computer IBM", limit=3)
            self.assertTrue(response["query_relaxed"])
            self.assertEqual(response["results"][0]["document_id"], "enwiki:100")
            self.assertEqual(response["results"][0]["ordinal"], 0)
            self.assertEqual(response["results"][0]["ranking_reason"], "relaxed_exact_title")

    def test_technical_terms_search_as_documented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            for query, mode in (
                ("std::vector C++", "and"),
                ("C# .NET 8", "phrase"),
                ("foo_bar", "and"),
            ):
                with self.subTest(query=query):
                    results = search(database, query, limit=5, mode=mode)
                    self.assertEqual(results[0]["document_id"], "enwiki:102")
                    self.assertEqual(results[0]["query"], query)
                    self.assertEqual(results[0]["query_mode"], mode)

    def test_index_rejects_interrupted_input_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            stats_path = processed / "extraction-stats.json"
            stats = json.loads(stats_path.read_text())
            stats["completed"] = False
            stats["stop_reason"] = "interrupted"
            stats_path.write_text(json.dumps(stats))
            with self.assertRaisesRegex(ValueError, "allow_incomplete"):
                build_index(processed, database)
            build_index(processed, database, allow_incomplete=True)

    def test_independent_database_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, database = self.prepare(root)
            build_index(processed, database)
            result = verify_database(
                database,
                processed,
                smoke_queries=("Apollo Guidance Computer", "reciprocal rank fusion"),
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["documents"], 3)
            self.assertEqual(result["chunks"], result["fts_rows"])

    def test_corpus_neutral_records_can_be_indexed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "manuals"
            processed.mkdir()
            document = {
                "schema_version": 1,
                "document_id": "manual:device:1",
                "corpus": "manuals",
                "title": "Device Service Manual",
                "source_url": "file:///manual.pdf",
                "source_version": "2026",
                "source_timestamp": "2026-01-01T00:00:00Z",
                "license": "proprietary",
                "content_hash": None,
                "attributes": {"manufacturer": "Example", "model": "D1"},
            }
            chunk = {
                "schema_version": 1,
                "chunk_instance_id": "manual-instance-1",
                "content_id": "sha256:abc",
                "document_id": "manual:device:1",
                "parent_chunk_id": None,
                "ordinal": 0,
                "heading_path": ["Troubleshooting", "Error codes"],
                "text": "Error E23 indicates a blocked intake.",
                "character_count": 37,
                "token_count": None,
                "previous_chunk_id": None,
                "next_chunk_id": None,
                "attributes": {"page": 142},
            }
            (processed / "documents.jsonl").write_text(json.dumps(document) + "\n")
            (processed / "chunks.jsonl").write_text(json.dumps(chunk) + "\n")
            database = root / "manuals.sqlite3"
            build_index(processed, database)
            result = search(database, "E23 blocked intake", limit=3)[0]
            self.assertEqual(result["document_id"], "manual:device:1")
            self.assertEqual(result["corpus"], "manuals")
            self.assertIn("Troubleshooting > Error codes", result["citation"])

    def test_pdf_front_matter_matches_are_ranked_after_body_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "manual"
            processed.mkdir()
            document = {
                "schema_version": 1,
                "document_id": "manual:1",
                "corpus": "manuals",
                "title": "Drawing Manual",
                "source_url": "https://example.test/manual.pdf",
                "source_version": "1",
                "source_timestamp": None,
                "license": "test",
                "content_hash": None,
                "attributes": {},
            }
            texts = [
                ("contents", ["Page vii"], {"front_matter": True}),
                ("body", ["Line conventions", "Page 4-18"], {}),
            ]
            chunks = []
            for ordinal, (name, heading, attributes) in enumerate(texts):
                text = "Hidden lines identify invisible edges in aircraft drawings."
                chunks.append(
                    {
                        "schema_version": 1,
                        "chunk_instance_id": name,
                        "content_id": f"sha256:{name}",
                        "document_id": "manual:1",
                        "parent_chunk_id": None,
                        "ordinal": ordinal,
                        "heading_path": heading,
                        "text": text,
                        "character_count": len(text),
                        "token_count": None,
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "attributes": attributes,
                    }
                )
            (processed / "documents.jsonl").write_text(json.dumps(document) + "\n", encoding="utf-8")
            (processed / "chunks.jsonl").write_text(
                "".join(json.dumps(chunk) + "\n" for chunk in chunks), encoding="utf-8"
            )
            database = root / "manual.sqlite3"
            build_index(processed, database)
            results = search(database, "hidden lines aircraft drawings", limit=2)
            self.assertEqual(results[0]["chunk_id"], "body")
            self.assertFalse(results[0]["front_matter"])
            self.assertEqual(results[1]["chunk_id"], "contents")
            self.assertTrue(results[1]["front_matter"])


if __name__ == "__main__":
    unittest.main()
