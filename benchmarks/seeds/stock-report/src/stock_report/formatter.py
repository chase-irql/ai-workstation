from collections.abc import Iterable

from .models import Item


def format_inventory(items: Iterable[Item]) -> str:
    lines = ["SKU | NAME | QTY"]
    lines.extend(f"{item.sku} | {item.name} | {item.quantity}" for item in items)
    return "\n".join(lines)


def format_low_stock(items: Iterable[Item]) -> str:
    """Render a low-stock report including reorder levels."""
    raise NotImplementedError
