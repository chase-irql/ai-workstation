import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config_loader import resolve_config


class ConfigLoaderTests(unittest.TestCase):
    def test_documented_precedence(self):
        result = resolve_config(
            {"host": "localhost", "port": 8000, "debug": False},
            {"port": 8100, "debug": True},
            {"port": 8200},
            {"port": 8300},
        )
        self.assertEqual(result, {"host": "localhost", "port": 8300, "debug": True})

    def test_missing_cli_value_does_not_erase_environment(self):
        result = resolve_config(
            {"region": "local"},
            {},
            {"region": "us-east"},
            {"region": None},
        )
        self.assertEqual(result["region"], "us-east")

    def test_new_keys_are_preserved(self):
        result = resolve_config({}, {"file_only": 1}, {"env_only": 2}, {"cli_only": 3})
        self.assertEqual(result, {"file_only": 1, "env_only": 2, "cli_only": 3})


if __name__ == "__main__":
    unittest.main()
