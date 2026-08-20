from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.dataset_registry import load_registry, storage_summary


class DatasetRegistryTests(unittest.TestCase):
    def test_project_registry_is_valid_and_budgeted(self):
        path = Path(__file__).resolve().parents[2] / "config" / "datasets.json"
        datasets = load_registry(path)
        self.assertEqual(len(datasets), 6)
        self.assertEqual(datasets[0].dataset_id, "python-3.14-docs")
        summary = storage_summary(datasets)
        self.assertLess(summary["download_max_bytes"], 4_000_000_000)
        self.assertLess(summary["indexed_max_bytes"], 15_000_000_000)

    def test_duplicate_ids_and_escaping_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = {
                "dataset_id": "example",
                "name": "Example",
                "description": "Example data",
                "category": "docs",
                "official_source_url": "https://example.invalid/docs",
                "license": "test",
                "attribution": "test",
                "release": "1",
                "update_frequency": "annual",
                "scope": "all",
                "formats": ["HTML"],
                "acquisition": {"method": "http", "location": "https://example.invalid/a.zip"},
                "storage": {
                    "download_min_bytes": 1,
                    "download_max_bytes": 2,
                    "extracted_max_bytes": 3,
                    "indexed_max_bytes": 4,
                },
                "paths": {"raw": "raw/example", "processed": "processed/example", "index": "index/example"},
                "status": "planned",
                "notes": "",
            }
            registry = root / "datasets.json"
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [template, template]}))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_registry(registry)
            escaping = dict(template)
            escaping["paths"] = dict(template["paths"], raw="../escape")
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [escaping]}))
            with self.assertRaisesRegex(ValueError, "project root"):
                load_registry(registry)


if __name__ == "__main__":
    unittest.main()
