from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.rsync_acquisition import validate_snapshot, windows_path_to_wsl, write_inventory


class RsyncAcquisitionTests(unittest.TestCase):
    def test_windows_path_conversion(self):
        with patch.object(Path, "resolve", return_value=Path("D:/ai-workstation/corpora/raw")):
            self.assertEqual(windows_path_to_wsl(Path("D:/ignored")), "/mnt/d/ai-workstation/corpora/raw")

    def test_inventory_validation_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rfc1.txt").write_text("Host Software", encoding="utf-8")
            (root / "bcp").mkdir()
            (root / "bcp" / "bcp-index.txt").write_text("index", encoding="utf-8")
            identity = write_inventory(root)
            manifest = {
                "schema_version": 1,
                "dataset_id": "rfc-editor-text",
                **identity,
            }
            (root / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(validate_snapshot(root)["files"], 2)
            (root / "rfc1.txt").write_text("corrupt", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "validation failed"):
                validate_snapshot(root)


if __name__ == "__main__":
    unittest.main()
