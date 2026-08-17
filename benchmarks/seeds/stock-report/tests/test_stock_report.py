import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_report import Item, low_stock
from stock_report.cli import main
from stock_report.formatter import format_inventory, format_low_stock


class StockReportTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            Item("z-9", "Washers", 9, 3),
            Item("B-2", "Bolts", 2, 5),
            Item("a-1", "Adapters", 4, 4),
        ]

    def test_existing_inventory_report_is_unchanged(self):
        self.assertEqual(
            format_inventory(self.items),
            "SKU | NAME | QTY\nz-9 | Washers | 9\nB-2 | Bolts | 2\na-1 | Adapters | 4",
        )

    def test_low_stock_includes_threshold_and_sorts_sku(self):
        self.assertEqual(low_stock(self.items), [self.items[2], self.items[1]])

    def test_low_stock_formatter(self):
        self.assertEqual(
            format_low_stock(low_stock(self.items)),
            "SKU | NAME | QTY | REORDER\na-1 | Adapters | 4 | 4\nB-2 | Bolts | 2 | 5",
        )

    def test_cli_low_stock_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps([item.__dict__ for item in self.items]), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                result = main(["--low-stock", str(path)])
        self.assertEqual(result, 0)
        self.assertEqual(
            output.getvalue().strip(),
            "SKU | NAME | QTY | REORDER\na-1 | Adapters | 4 | 4\nB-2 | Bolts | 2 | 5",
        )


if __name__ == "__main__":
    unittest.main()
