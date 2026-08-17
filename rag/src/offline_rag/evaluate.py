from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from .bm25 import search


def evaluate(database: Path, suite_path: Path) -> dict[str, object]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    candidate_chunks = int(suite.get("candidate_chunks", 50))
    cutoff = int(suite.get("document_cutoff", 5))
    reciprocal_rank = 0.0
    recalled = 0
    cases = []
    for case in suite["cases"]:
        started = time.perf_counter()
        chunks = search(database, case["query"], candidate_chunks)
        latency_ms = (time.perf_counter() - started) * 1000
        titles = []
        for chunk in chunks:
            if chunk["title"] not in titles:
                titles.append(chunk["title"])
        rank = next(
            (index + 1 for index, title in enumerate(titles) if title in case["expected_titles"]),
            None,
        )
        if rank is not None:
            reciprocal_rank += 1.0 / rank
            if rank <= cutoff:
                recalled += 1
        cases.append(
            {
                "query": case["query"],
                "expected_titles": case["expected_titles"],
                "rank": rank,
                "top_titles": titles[:cutoff],
                "recalled_at_cutoff": rank is not None and rank <= cutoff,
                "latency_ms": round(latency_ms, 3),
            }
        )
    count = len(cases)
    latencies = [case["latency_ms"] for case in cases]
    return {
        "schema_version": 1,
        "suite": suite["name"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database.resolve()),
        "queries": count,
        "candidate_chunks": candidate_chunks,
        "document_cutoff": cutoff,
        "recall_at_cutoff": round(recalled / count, 4) if count else 0,
        "mean_reciprocal_rank": round(reciprocal_rank / count, 4) if count else 0,
        "mean_latency_ms": round(statistics.mean(latencies), 3) if latencies else 0,
        "max_latency_ms": round(max(latencies), 3) if latencies else 0,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a Wikipedia retrieval index.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.database, args.suite)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
