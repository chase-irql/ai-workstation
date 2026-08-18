"""CPU-first, corpus-neutral retrieval components for the offline knowledge system."""

from typing import TYPE_CHECKING, Any

from .records import CommonChunk, CommonDocument

if TYPE_CHECKING:
    from .retrieval import index_status, retrieve_document

__all__ = ["CommonChunk", "CommonDocument", "index_status", "retrieve_document"]
__version__ = "0.8.0"


def __getattr__(name: str) -> Any:
    """Load retrieval helpers lazily so module CLIs do not pre-import BM25."""

    if name in {"index_status", "retrieve_document"}:
        from . import retrieval

        return getattr(retrieval, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
