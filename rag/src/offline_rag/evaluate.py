from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bm25 import QUERY_MODES, read_index_metadata, search


EVALUATION_SCHEMA_VERSION = 2


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return ordered[index]


def ranking_metrics(
    ranked_ids: Sequence[str],
    relevance: Mapping[str, int],
    success_cutoffs: Sequence[int] = (1, 5, 10),
    recall_cutoffs: Sequence[int] = (5, 10),
    mrr_cutoff: int = 10,
    ndcg_cutoff: int | None = 10,
) -> dict[str, float]:
    """Calculate document-level IR metrics for one deterministic ranking."""

    return ranking_metrics_grouped(
        [(value,) for value in ranked_ids],
        relevance,
        success_cutoffs,
        recall_cutoffs,
        mrr_cutoff,
        ndcg_cutoff,
    )


def ranking_metrics_grouped(
    ranked_id_groups: Sequence[Sequence[str]],
    relevance: Mapping[str, int],
    success_cutoffs: Sequence[int] = (1, 5, 10),
    recall_cutoffs: Sequence[int] = (5, 10),
    mrr_cutoff: int = 10,
    ndcg_cutoff: int | None = 10,
) -> dict[str, float]:
    """Calculate metrics where one evidence result may preserve alternate source IDs."""

    relevant_ids = set(relevance)
    if not relevant_ids:
        raise ValueError("relevance must not be empty")
    values: dict[str, float] = {}
    for cutoff in success_cutoffs:
        values[f"success_at_{cutoff}"] = float(
            any(relevant_ids.intersection(group) for group in ranked_id_groups[:cutoff])
        )
    for cutoff in recall_cutoffs:
        found_ids: set[str] = set()
        for group in ranked_id_groups[:cutoff]:
            found_ids.update(relevant_ids.intersection(group))
        found = len(found_ids)
        values[f"recall_at_{cutoff}"] = found / len(relevant_ids)
    first_rank = next(
        (
            rank
            for rank, group in enumerate(ranked_id_groups[:mrr_cutoff], start=1)
            if relevant_ids.intersection(group)
        ),
        None,
    )
    values[f"mrr_at_{mrr_cutoff}"] = 1.0 / first_rank if first_rank is not None else 0.0
    if ndcg_cutoff is not None:
        seen_relevant: set[str] = set()
        gains: list[int] = []
        for group in ranked_id_groups[:ndcg_cutoff]:
            matching = relevant_ids.intersection(group) - seen_relevant
            gains.append(max((int(relevance[item]) for item in matching), default=0))
            seen_relevant.update(matching)
        dcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
        ideal = sorted((int(value) for value in relevance.values()), reverse=True)[:ndcg_cutoff]
        idcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
        values[f"ndcg_at_{ndcg_cutoff}"] = dcg / idcg if idcg else 0.0
    return values


def _positive_cutoffs(values: object, name: str) -> list[int]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a nonempty list")
    result = [int(value) for value in values]
    if any(value < 1 for value in result):
        raise ValueError(f"{name} must contain only positive integers")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate cutoffs")
    return sorted(result)


def validate_suite(suite: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize legacy or version-2 evaluation suites."""

    cases_value = suite.get("cases")
    if not isinstance(cases_value, list) or not cases_value:
        raise ValueError("Evaluation suite must contain a nonempty cases list")
    schema_version = int(suite.get("schema_version", 1))
    if schema_version not in {1, EVALUATION_SCHEMA_VERSION}:
        raise ValueError(f"Unsupported evaluation suite schema version: {schema_version}")
    candidate_chunks = int(suite.get("candidate_chunks", 50))
    if candidate_chunks < 10:
        raise ValueError("candidate_chunks must be at least 10 for Success@10 and MRR@10")
    success_cutoffs = _positive_cutoffs(suite.get("success_cutoffs", [1, 5, 10]), "success_cutoffs")
    default_recall = [5, 10] + ([50] if candidate_chunks >= 50 else [])
    recall_cutoffs = _positive_cutoffs(suite.get("recall_cutoffs", default_recall), "recall_cutoffs")
    mrr_cutoff = int(suite.get("mrr_cutoff", 10))
    ndcg_cutoff = int(suite.get("ndcg_cutoff", 10))
    all_cutoffs = success_cutoffs + recall_cutoffs + [mrr_cutoff, ndcg_cutoff]
    if any(value < 1 for value in all_cutoffs):
        raise ValueError("All metric cutoffs must be positive")
    if max(all_cutoffs) > candidate_chunks:
        raise ValueError("candidate_chunks is insufficient for the requested metric cutoffs")
    default_mode = str(suite.get("query_mode", "and"))
    if default_mode not in QUERY_MODES:
        raise ValueError(f"Unsupported suite query_mode: {default_mode}")

    normalized_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, case_value in enumerate(cases_value, start=1):
        if not isinstance(case_value, Mapping):
            raise ValueError(f"Case {index} must be an object")
        query = case_value.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"Case {index} has an empty query")
        if schema_version == EVALUATION_SCHEMA_VERSION:
            query_id = case_value.get("id")
            if not isinstance(query_id, str) or not query_id.strip():
                raise ValueError(f"Version-2 case {index} requires a nonempty id")
        else:
            query_id = str(case_value.get("id") or f"legacy-{index:04d}")
        if query_id in seen_ids:
            raise ValueError(f"Duplicate query id: {query_id}")
        seen_ids.add(query_id)
        query_mode = str(case_value.get("query_mode", default_mode))
        if query_mode not in QUERY_MODES:
            raise ValueError(f"Case {query_id} has unsupported query_mode {query_mode!r}")
        relevance_value = case_value.get("relevance")
        expected_titles = case_value.get("expected_titles")
        if relevance_value is not None:
            if not isinstance(relevance_value, Mapping) or not relevance_value:
                raise ValueError(f"Case {query_id} relevance must be a nonempty object")
            relevance = {str(key): int(value) for key, value in relevance_value.items()}
            if any(value < 1 for value in relevance.values()):
                raise ValueError(f"Case {query_id} relevance grades must be positive")
            relevance_kind = "document_id"
        elif expected_titles is not None and schema_version == 1:
            if not isinstance(expected_titles, list) or not expected_titles or not all(
                isinstance(value, str) and value for value in expected_titles
            ):
                raise ValueError(f"Case {query_id} expected_titles must be a nonempty string list")
            relevance = {str(value): 1 for value in expected_titles}
            relevance_kind = "title"
        else:
            raise ValueError(f"Case {query_id} requires relevance or expected_titles")
        normalized_cases.append(
            {
                "id": query_id,
                "query": query,
                "query_type": str(case_value.get("query_type", "unspecified")),
                "query_mode": query_mode,
                "relevance": relevance,
                "relevance_kind": relevance_kind,
            }
        )
    return {
        "schema_version": schema_version,
        "name": str(suite.get("name") or "unnamed-suite"),
        "candidate_chunks": candidate_chunks,
        "success_cutoffs": success_cutoffs,
        "recall_cutoffs": recall_cutoffs,
        "mrr_cutoff": mrr_cutoff,
        "ndcg_cutoff": ndcg_cutoff,
        "cases": normalized_cases,
    }


def _deduplicate_documents(chunks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        document_id = str(chunk["document_id"])
        if document_id in seen:
            continue
        seen.add(document_id)
        document = {
            "document_id": document_id,
            "title": str(chunk["title"]),
            "chunk_id": str(chunk["chunk_id"]),
            "raw_score": float(chunk["raw_score"]),
            "citation": str(chunk["citation"]),
        }
        alternate_ids = chunk.get("alternate_document_ids")
        if isinstance(alternate_ids, list):
            document["alternate_document_ids"] = [str(value) for value in alternate_ids if value]
        alternate_sources = chunk.get("alternate_sources")
        if isinstance(alternate_sources, list):
            document["alternate_sources"] = [dict(value) for value in alternate_sources if isinstance(value, Mapping)]
        documents.append(document)
    return documents


def _aggregate(cases: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    if not cases:
        return {"queries": 0}
    metric_names = sorted(cases[0]["metrics"])
    values: dict[str, float | int] = {"queries": len(cases)}
    for name in metric_names:
        values[name] = round(statistics.mean(float(case["metrics"][name]) for case in cases), 6)
    latencies = [float(case["latency_ms"]) for case in cases]
    values.update(
        {
            "mean_latency_ms": round(statistics.mean(latencies), 3),
            "p50_latency_ms": round(percentile_nearest_rank(latencies, 50), 3),
            "p95_latency_ms": round(percentile_nearest_rank(latencies, 95), 3),
            "p99_latency_ms": round(percentile_nearest_rank(latencies, 99), 3),
            "max_latency_ms": round(max(latencies), 3),
        }
    )
    return values


DocumentRetriever = Callable[[str, int, str], Sequence[Mapping[str, Any]]]


def evaluate_retriever(
    suite_path: Path,
    retriever: DocumentRetriever,
    *,
    retrieval_identity: Mapping[str, Any],
) -> dict[str, object]:
    """Evaluate any document retriever with the same versioned metric contract."""

    raw_suite = json.loads(suite_path.read_text(encoding="utf-8"))
    if not isinstance(raw_suite, dict):
        raise ValueError("Evaluation suite root must be an object")
    suite = validate_suite(raw_suite)
    cases: list[dict[str, Any]] = []
    for case in suite["cases"]:
        started = time.perf_counter()
        chunks = retriever(case["query"], suite["candidate_chunks"], case["query_mode"])
        latency_ms = (time.perf_counter() - started) * 1000
        documents = _deduplicate_documents(chunks)
        if case["relevance_kind"] == "document_id":
            rank_groups = [
                [document["document_id"], *document.get("alternate_document_ids", [])]
                for document in documents
            ]
        else:
            rank_groups = [
                [
                    document["title"],
                    *[
                        str(source.get("title"))
                        for source in document.get("alternate_sources", [])
                        if source.get("title")
                    ],
                ]
                for document in documents
            ]
        metrics = ranking_metrics_grouped(
            rank_groups,
            case["relevance"],
            suite["success_cutoffs"],
            suite["recall_cutoffs"],
            suite["mrr_cutoff"],
            suite["ndcg_cutoff"] if case["relevance_kind"] == "document_id" else None,
        )
        cases.append(
            {
                "id": case["id"],
                "query": case["query"],
                "query_type": case["query_type"],
                "query_mode": case["query_mode"],
                "relevance_kind": case["relevance_kind"],
                "relevance": case["relevance"],
                "metrics": {key: round(value, 6) for key, value in sorted(metrics.items())},
                "top_documents": documents[: max(suite["success_cutoffs"] + suite["recall_cutoffs"])],
                "latency_ms": round(latency_ms, 3),
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["query_type"]].append(case)
    canonical_suite = json.dumps(raw_suite, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result: dict[str, object] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "suite": suite["name"],
        "suite_schema_version": suite["schema_version"],
        "suite_sha256": hashlib.sha256(canonical_suite.encode("utf-8")).hexdigest(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_chunks": suite["candidate_chunks"],
        "ranking_unit": "document",
        "aggregate": _aggregate(cases),
        "by_query_type": {key: _aggregate(grouped[key]) for key in sorted(grouped)},
        "cases": cases,
    }
    result.update(retrieval_identity)
    return result


def evaluate(database: Path, suite_path: Path) -> dict[str, object]:
    """Evaluate the SQLite BM25 baseline while preserving its public API."""

    return evaluate_retriever(
        suite_path,
        lambda query, limit, mode: search(database, query, limit, mode),
        retrieval_identity={
            "retriever": "sqlite_fts5_bm25",
            "database": str(database.resolve()),
            "index_metadata": read_index_metadata(database),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a corpus retrieval index.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.database, args.suite)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
