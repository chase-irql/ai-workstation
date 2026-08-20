from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .chunk_vector_index import load_chunk_vector_manifest
from .embeddings import OllamaEmbeddingClient, load_embedding_model_config
from .evaluate import evaluate_retriever
from .knowledge import KnowledgeCorpus, KnowledgeRuntime
from .retrieval_runtime import CachedEmbeddingProvider


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def evaluate_reranked_corpus(
    database: Path,
    vector_directory: Path,
    suite: Path,
    models: Path,
    *,
    model_id: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
) -> dict[str, object]:
    """Evaluate the same routed, hybrid, reranked path served through MCP."""

    config = load_embedding_model_config(models, model_id)
    provider = CachedEmbeddingProvider(OllamaEmbeddingClient(config, base_url=ollama_url), 256)
    runtime = KnowledgeRuntime(
        [
            KnowledgeCorpus(
                "evaluation-corpus",
                database,
                vector_directory=vector_directory,
                provider_factory=lambda: provider,
                default_retrieval="hybrid",
            )
        ]
    )
    try:
        return evaluate_retriever(
            suite,
            lambda query, limit, mode: runtime.search(
                query,
                limit=limit,
                mode=mode,
                corpus_ids=["evaluation-corpus"],
                retrieval="hybrid",
                rerank=True,
                deduplicate=True,
            )["results"],
            retrieval_identity={
                "retriever": "knowledge_hybrid_reranked",
                "reranker": "deterministic-evidence-v2",
                "database": str(database.resolve()),
                "vector_directory": str(vector_directory.resolve()),
                "vector_manifest": load_chunk_vector_manifest(vector_directory),
            },
        )
    finally:
        runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the end-to-end reranked knowledge path.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=Path("config/models.json"))
    parser.add_argument("--model-id")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_reranked_corpus(
        args.database,
        args.index,
        args.suite,
        args.models,
        model_id=args.model_id,
        ollama_url=args.ollama_url,
    )
    if args.output:
        _atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
