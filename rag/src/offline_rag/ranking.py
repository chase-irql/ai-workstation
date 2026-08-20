from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .records import normalize_content


TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._:/+#-][A-Za-z0-9]+)*", re.UNICODE)
QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "using",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
QUESTION_PREFIXES = frozenset(
    {
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "how",
        "is",
        "should",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would",
    }
)
EXACT_IDENTIFIER_RE = re.compile(
    r"(?:\b[A-Z][A-Z0-9_]{2,}\b|\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|"
    r"\b\w+::\w+\b|--[a-z0-9][\w-]*|(?i:\bRFC\s*)?\d{2,5}\b|\b\w+\.\w+\b|"
    r"(?i:\bC\+\+|\bC#|\.NET\b))",
)


@dataclass(frozen=True)
class QueryRoute:
    retrieval: str
    reason: str


def query_tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in TOKEN_RE.findall(text))


def meaningful_query_tokens(text: str) -> tuple[str, ...]:
    """Remove question scaffolding while retaining technical identifiers."""

    tokens = query_tokens(text)
    meaningful = tuple(token for token in tokens if token not in QUERY_STOPWORDS)
    return meaningful or tokens


def route_query(
    query: str,
    *,
    corpus_id: str,
    available_modes: Sequence[str],
    query_mode: str = "and",
) -> QueryRoute:
    """Choose exact lexical or hybrid retrieval using deterministic query features."""

    available = set(available_modes)
    if "hybrid" not in available:
        return QueryRoute("bm25", "semantic retrieval is not published for this corpus")
    if corpus_id == "iana-protocol-registries":
        return QueryRoute("bm25", "IANA registry rows are exact structured identifiers")
    if query_mode in {"phrase", "exact"} or '"' in query:
        return QueryRoute("bm25", "the query explicitly requests exact or phrase matching")
    identifiers = EXACT_IDENTIFIER_RE.findall(query)
    tokens = query_tokens(query)
    identifier_ratio = len({value.casefold() for value in identifiers}) / max(1, len(tokens))
    if identifiers and len(tokens) <= 8 and identifier_ratio >= 0.4:
        return QueryRoute("bm25", "the query is dominated by technical identifiers")
    meaningful = meaningful_query_tokens(query)
    if tokens and tokens[0] not in QUESTION_PREFIXES and len(tokens) <= 7 and len(meaningful) <= 5:
        return QueryRoute("bm25", "the query is a terse technical phrase")
    return QueryRoute("hybrid", "natural-language concepts benefit from lexical and semantic candidates")


def _coverage(query: set[str], value: object) -> float:
    if not query:
        return 0.0
    if isinstance(value, list):
        text = " ".join(str(part) for part in value)
    else:
        text = str(value or "")
    return len(query.intersection(query_tokens(text))) / len(query)


def rerank_results(query: str, values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rerank a bounded fused pool with transparent deterministic evidence features."""

    # The first-stage semantic/hybrid rank remains the dominant signal.  The
    # lexical features are deliberately bounded tie-breakers: large bonuses
    # caused common question words to demote strong paraphrase matches.
    query_set = set(meaningful_query_tokens(query))
    exact_identifiers = {value.casefold() for value in EXACT_IDENTIFIER_RE.findall(query)}
    ranked: list[dict[str, Any]] = []
    for original_position, value in enumerate(values):
        item = dict(value)
        title_coverage = _coverage(query_set, item.get("title"))
        heading_coverage = _coverage(query_set, item.get("heading_path"))
        text_coverage = _coverage(query_set, item.get("text"))
        searchable = " ".join(
            (
                str(item.get("title") or ""),
                " ".join(str(part) for part in item.get("heading_path") or []),
                str(item.get("text") or ""),
            )
        ).casefold()
        identifier_coverage = (
            sum(identifier in searchable for identifier in exact_identifiers) / len(exact_identifiers)
            if exact_identifiers
            else 0.0
        )
        fusion = item.get("fusion") if isinstance(item.get("fusion"), Mapping) else {}
        dual_retrieval = bool(fusion.get("lexical_rank") and fusion.get("semantic_rank"))
        exact_title = (
            item.get("ranking_reason") in {"exact_title", "relaxed_exact_title"}
            or item.get("pre_fusion_ranking_reason") in {"exact_title", "relaxed_exact_title"}
        )
        base = float(item.get("knowledge_fusion_score") or item.get("fusion_score") or 0.0)
        lexical_bonus = min(
            0.0015,
            0.008 * title_coverage
            + 0.004 * heading_coverage
            + 0.0015 * text_coverage
            + (0.002 if dual_retrieval else 0.0),
        )
        score = base + lexical_bonus + 0.035 * identifier_coverage + (0.10 if exact_title else 0.0)
        item["rerank_score"] = round(score, 12)
        item["rerank"] = {
            "method": "deterministic-evidence-v2",
            "meaningful_query_tokens": len(query_set),
            "base_score": base,
            "title_coverage": round(title_coverage, 6),
            "heading_coverage": round(heading_coverage, 6),
            "text_coverage": round(text_coverage, 6),
            "lexical_bonus": round(lexical_bonus, 12),
            "lexical_bonus_cap": 0.0015,
            "identifier_coverage": round(identifier_coverage, 6),
            "dual_retrieval": dual_retrieval,
            "exact_title": exact_title,
        }
        item["pre_rerank_position"] = original_position + 1
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            -float(item["rerank_score"]),
            int(item["pre_rerank_position"]),
            str(item.get("knowledge_corpus") or ""),
            str(item.get("document_id") or ""),
        )
    )
    for position, item in enumerate(ranked, start=1):
        item["rerank_position"] = position
    return ranked


def _fingerprint(item: Mapping[str, Any]) -> str:
    content_id = item.get("content_id")
    if isinstance(content_id, str) and content_id:
        return content_id
    text = normalize_content(str(item.get("text") or ""))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_set(item: Mapping[str, Any]) -> set[str]:
    return set(query_tokens(normalize_content(str(item.get("text") or ""))))


def deduplicate_results(
    values: Sequence[Mapping[str, Any]],
    *,
    similarity_threshold: float = 0.92,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove exact content duplicates and near-identical evidence passages."""

    if not 0.5 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0.5 and 1.0")
    retained: list[dict[str, Any]] = []
    retained_fingerprints: set[str] = set()
    retained_tokens: list[set[str]] = []
    removed: list[dict[str, Any]] = []
    for value in values:
        item = dict(value)
        fingerprint = _fingerprint(item)
        reason: str | None = None
        duplicate_of: str | None = None
        duplicate_index: int | None = None
        if fingerprint in retained_fingerprints:
            reason = "content_id"
            duplicate_index = next(
                index for index, existing in enumerate(retained) if _fingerprint(existing) == fingerprint
            )
            duplicate_of = str(retained[duplicate_index].get("chunk_id"))
        else:
            tokens = _token_set(item)
            if len(tokens) >= 12:
                for index, prior in enumerate(retained_tokens):
                    union = tokens | prior
                    similarity = len(tokens & prior) / len(union) if union else 0.0
                    if similarity >= similarity_threshold:
                        reason = f"token_jaccard:{similarity:.4f}"
                        duplicate_index = index
                        duplicate_of = str(retained[index].get("chunk_id"))
                        break
        if reason is not None:
            assert duplicate_index is not None
            alternate = {
                "document_id": item.get("document_id"),
                "chunk_id": item.get("chunk_id"),
                "knowledge_corpus": item.get("knowledge_corpus"),
                "title": item.get("title"),
                "citation": item.get("citation"),
                "source_url": item.get("source_url"),
            }
            retained[duplicate_index].setdefault("alternate_sources", []).append(alternate)
            alternate_ids = retained[duplicate_index].setdefault("alternate_document_ids", [])
            alternate_document_id = item.get("document_id")
            if alternate_document_id and alternate_document_id not in alternate_ids:
                alternate_ids.append(alternate_document_id)
            removed.append(
                {
                    "chunk_id": item.get("chunk_id"),
                    "document_id": item.get("document_id"),
                    "knowledge_corpus": item.get("knowledge_corpus"),
                    "duplicate_of": duplicate_of,
                    "reason": reason,
                }
            )
            continue
        retained.append(item)
        retained_fingerprints.add(fingerprint)
        retained_tokens.append(_token_set(item))
    return retained, removed
