from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.manifest import create_manifest


class ManifestTests(unittest.TestCase):
    def prepare(self, root: Path, corrupt: bool = False) -> None:
        prefix = "enwiki-20260801"
        files = {
            f"{prefix}-pages-articles-multistream.xml.bz2": b"archive",
            f"{prefix}-pages-articles-multistream-index.txt.bz2": b"index",
        }
        lines = []
        for name, content in files.items():
            (root / name).write_bytes(content)
            digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()
            if corrupt and name.endswith("xml.bz2"):
                digest = "0" * 40
            lines.append(f"{digest}  {name}")
        (root / f"{prefix}-sha1sums.txt").write_text("\n".join(lines) + "\n")

    def test_checksum_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            manifest = create_manifest(root, "20260801")
            self.assertTrue(all(item["verified"] for item in manifest["files"]))
            self.assertTrue((root / "manifest.json").is_file())
            self.assertIn("sha256", manifest["checksum_file"])

    def test_checksum_failure_does_not_publish_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root, corrupt=True)
            with self.assertRaisesRegex(ValueError, "SHA1 mismatch"):
                create_manifest(root, "20260801")
            self.assertFalse((root / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()

