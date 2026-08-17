from collections.abc import Iterable

from .models import Item


def low_stock(items: Iterable[Item]) -> list[Item]:
    """Return low-stock items ordered case-insensitively by SKU."""
    raise NotImplementedError
