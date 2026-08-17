import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledger_cli import net_total


class NetTotalTests(unittest.TestCase):
    def test_charges_and_refunds_preserve_sign(self):
        amounts = [Decimal("100.00"), Decimal("-20.00"), Decimal("5.50")]
        self.assertEqual(net_total(amounts), Decimal("85.50"))

    def test_empty_ledger_is_zero(self):
        self.assertEqual(net_total([]), Decimal("0"))


if __name__ == "__main__":
    unittest.main()

