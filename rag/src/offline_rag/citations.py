from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _markdown_label(value: str) -> str:
    """Escape the small set of characters that can alter a Markdown link label."""

    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def copy_ready_citation(item: Mapping[str, Any]) -> str:
    """Render one citation as Markdown without reconstructing its source URL."""

    citation = str(item.get("citation") or "").strip()
    source_url = str(item.get("source_url") or "").strip()
    if not source_url:
        return citation
    suffix = f" {source_url}"
    label = citation[: -len(suffix)] if citation.endswith(suffix) else citation
    label = label.strip() or str(item.get("title") or "Source").strip() or "Source"
    # An angle-bracket destination keeps punctuation such as parentheses out of
    # Markdown's link grammar. Most importantly, the URL is copied byte-for-byte.
    return f"[{_markdown_label(label)}](<{source_url}>)"


def add_copy_ready_citations(
    result: dict[str, Any],
    items: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Attach stable references and a deduplicated, ready-to-copy source block."""

    sources: list[dict[str, str]] = []
    source_positions: dict[tuple[str, str], int] = {}
    for item in items:
        citation = str(item.get("citation") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        if not citation and not source_url:
            continue
        key = (citation, source_url)
        position = source_positions.get(key)
        if position is None:
            position = len(sources) + 1
            source_positions[key] = position
            reference = f"S{position}"
            sources.append(
                {
                    "reference": reference,
                    "citation": citation,
                    "source_url": source_url,
                    "citation_markdown": f"[{reference}] {copy_ready_citation(item)}",
                }
            )
        item["citation_reference"] = f"S{position}"
        item["citation_markdown"] = sources[position - 1]["citation_markdown"]

    result["copy_ready_citations"] = {
        "usage": (
            "Cite with [S#] in prose, then copy the matching citation_markdown value "
            "verbatim into the Sources list. Never reconstruct or retype its URL."
        ),
        "sources": sources,
    }
    return result
