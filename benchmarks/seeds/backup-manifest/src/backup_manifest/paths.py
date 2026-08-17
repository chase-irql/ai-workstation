import re
from collections.abc import Iterable


def normalize_path(path: str) -> str:
    """Return the platform-independent representation stored in manifests."""
    normalized = re.sub(r"[/\\]+", "/", path.strip())
    return normalized.lstrip("./")


def is_excluded(path: str, patterns: Iterable[str]) -> bool:
    """Return whether a manifest path matches an exclusion component."""
    normalized = normalize_path(path).casefold()
    return any(normalize_path(pattern).casefold() in normalized for pattern in patterns)
