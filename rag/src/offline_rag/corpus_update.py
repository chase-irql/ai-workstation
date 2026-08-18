from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bm25 import read_index_metadata
from .vector_index import DocumentEmbeddingRecord, embedding_text_sha256, iter_document_embedding_records


UPDATE_PLAN_SCHEMA_VERSION = 1


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _next(iterator: Iterator[DocumentEmbeddingRecord]) -> DocumentEmbeddingRecord | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def plan_vector_update(
    previous_database: Path,
    new_database: Path,
    *,
    max_chunks: int = 1,
    max_characters: int = 4_000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Compare exact embedding inputs with constant memory and estimate reusable vectors."""

    if max_chunks < 1:
        raise ValueError("max_chunks must be positive")
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    if sample_limit < 0:
        raise ValueError("sample_limit cannot be negative")
    previous_metadata = read_index_metadata(previous_database)
    new_metadata = read_index_metadata(new_database)
    previous_iterator = iter(
        iter_document_embedding_records(
            previous_database,
            max_chunks=max_chunks,
            max_characters=max_characters,
        )
    )
    new_iterator = iter(
        iter_document_embedding_records(
            new_database,
            max_chunks=max_chunks,
            max_characters=max_characters,
        )
    )
    previous = _next(previous_iterator)
    current = _next(new_iterator)
    counts = {"unchanged": 0, "modified": 0, "added": 0, "deleted": 0}
    samples: dict[str, list[str]] = {key: [] for key in counts}

    def record(kind: str, document_id: str) -> None:
        counts[kind] += 1
        if len(samples[kind]) < sample_limit:
            samples[kind].append(document_id)

    while previous is not None or current is not None:
        if previous is None:
            assert current is not None
            record("added", current.document_id)
            current = _next(new_iterator)
        elif current is None:
            record("deleted", previous.document_id)
            previous = _next(previous_iterator)
        elif previous.document_id < current.document_id:
            record("deleted", previous.document_id)
            previous = _next(previous_iterator)
        elif current.document_id < previous.document_id:
            record("added", current.document_id)
            current = _next(new_iterator)
        else:
            kind = (
                "unchanged"
                if embedding_text_sha256(previous.embedding_text) == embedding_text_sha256(current.embedding_text)
                else "modified"
            )
            record(kind, current.document_id)
            previous = _next(previous_iterator)
            current = _next(new_iterator)

    previous_searchable = counts["unchanged"] + counts["modified"] + counts["deleted"]
    new_searchable = counts["unchanged"] + counts["modified"] + counts["added"]
    embed_required = counts["modified"] + counts["added"]
    return {
        "schema_version": UPDATE_PLAN_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous": {
            "database": str(previous_database.resolve()),
            "build_id": previous_metadata.get("build_id"),
            "source_versions": previous_metadata.get("source_versions", []),
            "searchable_documents": previous_searchable,
        },
        "new": {
            "database": str(new_database.resolve()),
            "build_id": new_metadata.get("build_id"),
            "source_versions": new_metadata.get("source_versions", []),
            "searchable_documents": new_searchable,
        },
        "representation": {"max_chunks": max_chunks, "max_characters": max_characters},
        "changes": counts,
        "embedding_work": {
            "vectors_reusable": counts["unchanged"],
            "vectors_to_embed": embed_required,
            "reuse_rate": round(counts["unchanged"] / new_searchable, 8) if new_searchable else 0.0,
        },
        "sample_document_ids": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan a corpus generation update without loading a model.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--previous-database", type=Path, required=True)
    plan.add_argument("--new-database", type=Path, required=True)
    plan.add_argument("--max-chunks", type=int, default=1)
    plan.add_argument("--max-characters", type=int, default=4_000)
    plan.add_argument("--sample-limit", type=int, default=20)
    plan.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = plan_vector_update(
        args.previous_database,
        args.new_database,
        max_chunks=args.max_chunks,
        max_characters=args.max_characters,
        sample_limit=args.sample_limit,
    )
    if args.output is not None:
        _atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
