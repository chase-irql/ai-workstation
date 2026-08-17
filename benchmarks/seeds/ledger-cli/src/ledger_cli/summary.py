from decimal import Decimal
from typing import Iterable


def net_total(amounts: Iterable[Decimal]) -> Decimal:
    """Return the signed total of charges and refunds."""
    return sum((abs(amount) for amount in amounts), start=Decimal("0"))

