from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.ranking import deduplicate_results, rerank_results, route_query


class RankingTests(unittest.TestCase):
    def test_query_routing_prefers_exact_identifiers_and_hybrid_concepts(self):
        available = ("bm25", "semantic", "hybrid")
        exact = route_query(
            "openat2 RESOLVE_BENEATH",
            corpus_id="linux-man-pages",
            available_modes=available,
        )
        self.assertEqual(exact.retrieval, "bm25")
        conceptual = route_query(
            "how does a task group cancel sibling coroutines after one fails",
            corpus_id="python-3.14-docs",
            available_modes=available,
        )
        self.assertEqual(conceptual.retrieval, "hybrid")
        acronym_concept = route_query(
            "how does CPU scheduling distribute work across processor cores",
            corpus_id="linux-man-pages",
            available_modes=available,
        )
        self.assertEqual(acronym_concept.retrieval, "hybrid")
        iana = route_query(
            "what port is secure web traffic assigned",
            corpus_id="iana-protocol-registries",
            available_modes=available,
        )
        self.assertEqual(iana.retrieval, "bm25")

    def test_reranker_is_deterministic_and_exposes_components(self):
        values = [
            {
                "document_id": "b",
                "chunk_id": "b1",
                "knowledge_corpus": "docs",
                "title": "Unrelated",
                "heading_path": [],
                "text": "general background",
                "knowledge_fusion_score": 0.011,
            },
            {
                "document_id": "a",
                "chunk_id": "a1",
                "knowledge_corpus": "docs",
                "title": "TaskGroup cancellation",
                "heading_path": ["asyncio"],
                "text": "Cancel sibling tasks when one coroutine fails.",
                "knowledge_fusion_score": 0.01,
            },
        ]
        first = rerank_results("taskgroup cancel sibling coroutine", values)
        second = rerank_results("taskgroup cancel sibling coroutine", values)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["document_id"], "a")
        self.assertEqual(first[0]["rerank"]["method"], "deterministic-evidence-v2")
        self.assertEqual(first[0]["rerank"]["meaningful_query_tokens"], 4)

    def test_reranker_does_not_reward_question_scaffolding(self):
        values = [
            {
                "document_id": "semantic",
                "chunk_id": "semantic-1",
                "knowledge_corpus": "docs",
                "title": "Encrypted Handshake Key Schedule",
                "heading_path": [],
                "text": "Derive traffic secrets for each handshake phase.",
                "knowledge_fusion_score": 1.0 / 63.0,
            },
            {
                "document_id": "scaffolding",
                "chunk_id": "scaffolding-1",
                "knowledge_corpus": "docs",
                "title": "How the system is used",
                "heading_path": ["What it does"],
                "text": "The phases of a general process are described here.",
                "knowledge_fusion_score": 1.0 / 70.0,
            },
        ]
        ranked = rerank_results(
            "how are traffic secrets derived across the phases of an encrypted handshake",
            values,
        )
        self.assertEqual(ranked[0]["document_id"], "semantic")

    def test_deduplication_removes_content_and_near_duplicates(self):
        common = "This sufficiently long technical passage explains reciprocal rank fusion over independent ranked lists."
        values = [
            {"chunk_id": "one", "document_id": "a", "text": common, "content_id": "sha256:same"},
            {"chunk_id": "two", "document_id": "b", "text": common, "content_id": "sha256:same"},
            {
                "chunk_id": "three",
                "document_id": "c",
                "text": "A completely different passage discusses lunar guidance computer memory and navigation.",
                "content_id": "sha256:different",
            },
        ]
        retained, removed = deduplicate_results(values)
        self.assertEqual([item["chunk_id"] for item in retained], ["one", "three"])
        self.assertEqual(removed[0]["duplicate_of"], "one")
        self.assertEqual(removed[0]["reason"], "content_id")
        self.assertEqual(retained[0]["alternate_document_ids"], ["b"])
        self.assertEqual(retained[0]["alternate_sources"][0]["chunk_id"], "two")


if __name__ == "__main__":
    unittest.main()
