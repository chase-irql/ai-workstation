from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingProvider
from .ranking import deduplicate_results, rerank_results, route_query
from .retrieval import retrieve_chunk_context, retrieve_document
from .retrieval_runtime import RETRIEVAL_MODES, RetrievalRuntime, RetrievalUnavailableError


@dataclass(frozen=True)
class KnowledgeCorpus:
    """Configuration for one independently replaceable retrieval index."""

    corpus_id: str
    database: Path
    vector_directory: Path | None = None
    provider_factory: Callable[[], EmbeddingProvider] | None = None
    default_retrieval: str = "bm25"


class KnowledgeRuntime:
    """Federate several immutable indexes without physically merging them."""

    def __init__(self, corpora: Sequence[KnowledgeCorpus], *, query_cache_size: int = 256) -> None:
        if not corpora:
            raise ValueError("at least one knowledge corpus is required")
        self._runtimes: OrderedDict[str, RetrievalRuntime] = OrderedDict()
        seen_databases: set[Path] = set()
        for corpus in corpora:
            corpus_id = corpus.corpus_id.strip()
            if not corpus_id or corpus_id in self._runtimes:
                raise ValueError(f"duplicate or empty corpus ID: {corpus.corpus_id!r}")
            database = corpus.database.resolve()
            if database in seen_databases:
                raise ValueError(f"database registered more than once: {database}")
            seen_databases.add(database)
            self._runtimes[corpus_id] = RetrievalRuntime(
                database,
                vector_directory=corpus.vector_directory,
                provider_factory=corpus.provider_factory,
                default_mode=corpus.default_retrieval,
                query_cache_size=query_cache_size,
            )

    @property
    def corpus_ids(self) -> tuple[str, ...]:
        return tuple(self._runtimes)

    def _select(self, corpus_ids: Sequence[str] | None) -> list[str]:
        if not corpus_ids:
            return list(self._runtimes)
        selected: list[str] = []
        for corpus_id in corpus_ids:
            if corpus_id not in self._runtimes:
                raise ValueError(
                    f"unknown corpus {corpus_id!r}; available corpora: {', '.join(self._runtimes)}"
                )
            if corpus_id not in selected:
                selected.append(corpus_id)
        return selected

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        mode: str = "and",
        corpus_ids: Sequence[str] | None = None,
        retrieval: str = "auto",
        rerank: bool = True,
        deduplicate: bool = True,
    ) -> dict[str, Any]:
        """Search selected corpora and fuse document ranks without comparing BM25 magnitudes."""

        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if len(query) > 2_000:
            raise ValueError("query must not exceed 2000 characters")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if mode not in {"and", "phrase", "exact"}:
            raise ValueError("mode must be and, phrase, or exact")
        if retrieval not in {"auto", "default", *RETRIEVAL_MODES}:
            raise ValueError("retrieval must be auto, default, bm25, semantic, or hybrid")

        selected = self._select(corpus_ids)
        # Reranking can only promote evidence that survives candidate generation.
        # Keep a bounded but meaningfully broader pool than the final response.
        per_corpus_limit = min(50, max(32, limit * 4))
        corpus_order = {corpus_id: index for index, corpus_id in enumerate(selected)}
        fused: list[dict[str, Any]] = []
        retrieval_state: dict[str, dict[str, Any]] = {}
        candidate_documents: dict[str, int] = {}
        for corpus_id in selected:
            runtime = self._runtimes[corpus_id]
            available = set(runtime.status()["available_modes"])
            route_reason = None
            if retrieval == "auto":
                route = route_query(
                    query,
                    corpus_id=corpus_id,
                    available_modes=tuple(available),
                    query_mode=mode,
                )
                requested = route.retrieval
                route_reason = route.reason
            else:
                requested = runtime.default_mode if retrieval == "default" else retrieval
            selected_mode = requested if requested in available else "bm25"
            fallback_reason = None
            if selected_mode != requested:
                fallback_reason = f"{requested} is not configured for this corpus"
            try:
                response = runtime.search(
                    query,
                    limit=per_corpus_limit,
                    query_mode=mode,
                    retrieval_mode=selected_mode,
                    candidate_limit=min(400, max(80, per_corpus_limit * 20)),
                    allow_relaxation=selected_mode != "bm25",
                )
            except RetrievalUnavailableError as error:
                if selected_mode == "bm25":
                    raise
                fallback_reason = str(error)
                selected_mode = "bm25"
                response = runtime.search(
                    query,
                    limit=per_corpus_limit,
                    query_mode=mode,
                    retrieval_mode="bm25",
                    candidate_limit=min(400, max(80, per_corpus_limit * 20)),
                    allow_relaxation=False,
                )
            results = list(response.get("results", []))
            candidate_documents[corpus_id] = len(results)
            retrieval_state[corpus_id] = {
                "requested": requested,
                "used": selected_mode,
                "fallback": fallback_reason is not None,
                "fallback_reason": fallback_reason,
                "route_reason": route_reason,
                "latency_ms": response.get("latency_ms"),
            }
            for rank, value in enumerate(results, 1):
                item = dict(value)
                source_fusion_score = item.get("fusion_score")
                item["knowledge_corpus"] = corpus_id
                item["corpus_rank"] = rank
                item["corpus_retrieval"] = selected_mode
                item["source_fusion_score"] = source_fusion_score
                item["knowledge_fusion_score"] = 1.0 / (60.0 + rank)
                fused.append(item)

        fused.sort(
            key=lambda item: (
                -int(item.get("ranking_reason") in {"exact_title", "relaxed_exact_title"}),
                -float(item["knowledge_fusion_score"]),
                corpus_order[str(item["knowledge_corpus"])],
                str(item["document_id"]),
            )
        )
        # A single-corpus BM25 ranking already compares candidates on one
        # calibrated scale. Semantic-oriented evidence bonuses can only
        # disturb that strong exact-search order; reserve reranking for hybrid,
        # semantic, or cross-corpus fusion where it adds a real second signal.
        apply_rerank = rerank and not (
            len(selected) == 1 and retrieval_state[selected[0]]["used"] == "bm25"
        )
        ranked = rerank_results(query, fused) if apply_rerank else fused
        removed_duplicates: list[dict[str, Any]] = []
        if deduplicate:
            ranked, removed_duplicates = deduplicate_results(ranked)
        return {
            "query": query,
            "mode": mode,
            "ranking_unit": "document",
            "fusion": "reciprocal_rank_per_corpus",
            "corpora_searched": selected,
            "candidate_documents": candidate_documents,
            "retrieval_by_corpus": retrieval_state,
            "reranker": "deterministic-evidence-v2" if apply_rerank else None,
            "deduplication": {
                "enabled": deduplicate,
                "removed_count": len(removed_duplicates),
                "removed": removed_duplicates,
            },
            "results": ranked[:limit],
        }

    def retrieve_document(
        self,
        corpus_id: str,
        document_id: str,
        *,
        chunk_offset: int,
        chunk_limit: int,
    ) -> dict[str, Any]:
        runtime = self._runtimes[self._select([corpus_id])[0]]
        result = retrieve_document(
            runtime.database,
            document_id,
            chunk_offset=chunk_offset,
            chunk_limit=chunk_limit,
        )
        result["knowledge_corpus"] = corpus_id
        return result

    def retrieve_context(self, corpus_id: str, chunk_id: str, *, before: int, after: int) -> dict[str, Any]:
        runtime = self._runtimes[self._select([corpus_id])[0]]
        result = retrieve_chunk_context(runtime.database, chunk_id, before=before, after=after)
        result["knowledge_corpus"] = corpus_id
        return result

    def status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "corpus_count": len(self._runtimes),
            "corpora": {
                corpus_id: {**runtime.lexical_status, "retrieval": runtime.status()}
                for corpus_id, runtime in self._runtimes.items()
            },
        }

    def close(self) -> None:
        for runtime in self._runtimes.values():
            runtime.close()


def corpus_mapping(corpora: Sequence[KnowledgeCorpus]) -> Mapping[str, Path]:
    """Return the stable corpus-to-database mapping for diagnostics."""

    return {corpus.corpus_id: corpus.database.resolve() for corpus in corpora}
