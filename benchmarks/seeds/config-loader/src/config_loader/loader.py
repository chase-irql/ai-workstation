from collections.abc import Mapping
from typing import Any

from .sources import overlay


def resolve_config(
    defaults: Mapping[str, Any],
    file_values: Mapping[str, Any],
    env_values: Mapping[str, Any],
    cli_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve all supported configuration sources into one mapping."""
    return overlay(defaults, file_values, env_values, cli_values)
