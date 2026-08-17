from collections.abc import Mapping
from typing import Any


def overlay(base: Mapping[str, Any], *layers: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay mappings in increasing order of precedence."""
    result = dict(base)
    for layer in reversed(layers):
        result.update(layer)
    return result
