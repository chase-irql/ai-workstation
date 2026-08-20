from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fixtures import write_archive
from offline_rag.bm25 import build_index
from offline_rag.evaluate import (
    evaluate,
    percentile_nearest_rank,
    ranking_metrics,
    ranking_metrics_grouped,
    validate_suite,
)
from offline_rag.wikipedia_dump import extract


class EvaluationTests(unittest.TestCase):
    def test_grouped_metrics_count_alternate_sources_at_the_retained_rank(self):
        metrics = ranking_metrics_grouped(
            [("primary", "relevant-a"), ("relevant-b",)],
            {"relevant-a": 3, "relevant-b": 1},
            success_cutoffs=(1, 2),
            recall_cutoffs=(1, 2),
            mrr_cutoff=2,
            ndcg_cutoff=2,
        )
        self.assertEqual(metrics["success_at_1"], 1.0)
        self.assertEqual(metrics["recall_at_1"], 0.5)
        self.assertEqual(metrics["recall_at_2"], 1.0)
        self.assertEqual(metrics["mrr_at_2"], 1.0)

    def test_hand_calculated_metrics(self):
        relevance = {"b": 3, "c": 1, "d": 2}
        metrics = ranking_metrics(
            ["a", "b", "c"],
            relevance,
            success_cutoffs=(1, 5),
            recall_cutoffs=(2, 5),
            mrr_cutoff=10,
            ndcg_cutoff=3,
        )
        expected_dcg = (2**3 - 1) / math.log2(3) + (2**1 - 1) / math.log2(4)
        expected_idcg = (
            (2**3 - 1) / math.log2(2)
            + (2**2 - 1) / math.log2(3)
            + (2**1 - 1) / math.log2(4)
        )
        self.assertEqual(metrics["success_at_1"], 0.0)
        self.assertEqual(metrics["success_at_5"], 1.0)
        self.assertAlmostEqual(metrics["recall_at_2"], 1 / 3)
        self.assertAlmostEqual(metrics["recall_at_5"], 2 / 3)
        self.assertEqual(metrics["mrr_at_10"], 0.5)
        self.assertAlmostEqual(metrics["ndcg_at_3"], expected_dcg / expected_idcg)

    def test_nearest_rank_percentiles(self):
        values = [1.0, 2.0, 3.0, 100.0]
        self.assertEqual(percentile_nearest_rank(values, 50), 2.0)
        self.assertEqual(percentile_nearest_rank(values, 95), 100.0)
        self.assertEqual(percentile_nearest_rank(values, 99), 100.0)

    def test_invalid_suites(self):
        with self.assertRaisesRegex(ValueError, "nonempty cases"):
            validate_suite({"schema_version": 2, "cases": []})
        base = {
            "schema_version": 2,
            "candidate_chunks": 10,
            "cases": [
                {"id": "duplicate", "query": "one", "relevance": {"doc:1": 1}},
                {"id": "duplicate", "query": "two", "relevance": {"doc:2": 1}},
            ],
        }
        with self.assertRaisesRegex(ValueError, "Duplicate query id"):
            validate_suite(base)
        insufficient = {
            "schema_version": 2,
            "candidate_chunks": 10,
            "recall_cutoffs": [50],
            "cases": [{"id": "one", "query": "one", "relevance": {"doc:1": 1}}],
        }
        with self.assertRaisesRegex(ValueError, "insufficient"):
            validate_suite(insufficient)
        with self.assertRaisesRegex(ValueError, "requires relevance"):
            validate_suite(
                {
                    "schema_version": 2,
                    "candidate_chunks": 10,
                    "cases": [{"id": "one", "query": "one"}],
                }
            )

    def prepare_database(self, root: Path) -> Path:
        processed = root / "processed"
        extract(write_archive(root), processed, "20260801", None, 3200)
        database = root / "index.sqlite3"
        build_index(processed, database)
        return database

    def test_version_two_suite_and_grouped_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = self.prepare_database(root)
            suite = {
                "schema_version": 2,
                "name": "synthetic-v2",
                "candidate_chunks": 10,
                "cases": [
                    {
                        "id": "agc-001",
                        "query": "rope memory",
                        "query_type": "factual",
                        "relevance": {"enwiki:100": 3, "enwiki:102": 1},
                    },
                    {
                        "id": "rrf-001",
                        "query": "reciprocal rank fusion",
                        "query_type": "conceptual",
                        "relevance": {"enwiki:102": 3},
                    },
                ],
            }
            suite_path = root / "suite.json"
            suite_path.write_text(json.dumps(suite))
            result = evaluate(database, suite_path)
            self.assertEqual(result["ranking_unit"], "document")
            self.assertEqual(result["aggregate"]["queries"], 2)
            self.assertEqual(result["aggregate"]["success_at_1"], 1.0)
            self.assertIn("ndcg_at_10", result["aggregate"])
            self.assertEqual(sorted(result["by_query_type"]), ["conceptual", "factual"])
            for name in ("mean_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "max_latency_ms"):
                self.assertIn(name, result["aggregate"])
            self.assertEqual(result["index_metadata"]["schema_version"], 2)

    def test_legacy_expected_titles_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = self.prepare_database(root)
            suite_path = root / "legacy.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "name": "legacy",
                        "candidate_chunks": 10,
                        "cases": [
                            {"query": "rope memory", "expected_titles": ["Apollo Guidance Computer"]}
                        ],
                    }
                )
            )
            result = evaluate(database, suite_path)
            self.assertEqual(result["suite_schema_version"], 1)
            self.assertEqual(result["aggregate"]["success_at_1"], 1.0)
            self.assertNotIn("ndcg_at_10", result["aggregate"])
            self.assertEqual(result["cases"][0]["id"], "legacy-0001")


if __name__ == "__main__":
    unittest.main()
