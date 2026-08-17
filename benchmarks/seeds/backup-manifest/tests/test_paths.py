import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backup_manifest import is_excluded, normalize_path


class PathTests(unittest.TestCase):
    def test_normalizes_windows_and_repeated_separators(self):
        self.assertEqual(normalize_path(r".\src\\data\file.txt"), "src/data/file.txt")

    def test_preserves_meaningful_leading_dot(self):
        self.assertEqual(normalize_path(".cache/index.bin"), ".cache/index.bin")
        self.assertEqual(normalize_path("../archive/file.txt"), "../archive/file.txt")

    def test_excludes_complete_directory_component(self):
        self.assertTrue(is_excluded(r"src\TMP\cache.bin", ["tmp"]))
        self.assertTrue(is_excluded(r"project\.cache\index.bin", [".cache"]))

    def test_does_not_match_substrings_inside_names(self):
        self.assertFalse(is_excluded("src/attempt.py", ["tmp"]))
        self.assertFalse(is_excluded("src/cacheable.py", ["cache"]))

    def test_matches_a_complete_filename_component(self):
        self.assertTrue(is_excluded("build/secrets.json", ["secrets.json"]))


if __name__ == "__main__":
    unittest.main()
