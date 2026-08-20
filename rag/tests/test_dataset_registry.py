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
        self.assertEqual(len(datasets), 54)
        dataset_ids = {dataset.dataset_id for dataset in datasets}
        self.assertIn("devops-stackexchange", dataset_ids)
        self.assertIn("security-stackexchange", dataset_ids)
        self.assertIn("bash-5.3-manual", dataset_ids)
        self.assertIn("faa-amt-general-2023", dataset_ids)
        self.assertIn("cmake-4.4-docs", dataset_ids)
        self.assertIn("openssl-4.0-docs", dataset_ids)
        self.assertIn("openssh-10.5p1-docs", dataset_ids)
        self.assertIn("ninja-1.13-docs", dataset_ids)
        self.assertIn("postgresql-18-docs", dataset_ids)
        self.assertIn("systemd-261-docs", dataset_ids)
        self.assertIn("nodejs-24-docs", dataset_ids)
        self.assertIn("apache-httpd-2.4-docs", dataset_ids)
        self.assertIn("docker-docs-20260820", dataset_ids)
        self.assertIn("kubernetes-docs-20260820", dataset_ids)
        self.assertIn("rust-1.97-docs", dataset_ids)
        self.assertIn("typescript-docs-20260820", dataset_ids)
        self.assertIn("gdb-17.2-manual", dataset_ids)
        self.assertIn("gcc-16.2-manual", dataset_ids)
        self.assertIn("cpp-16.2-manual", dataset_ids)
        self.assertIn("linux-kernel-7.2-docs", dataset_ids)
        self.assertIn("llvm-project-22.1.8-docs", dataset_ids)
        self.assertIn("go-1.26.7-docs", dataset_ids)
        self.assertIn("podman-6.1-docs", dataset_ids)
        self.assertIn("binutils-2.47-docs", dataset_ids)
        self.assertTrue(
            {
                "coreutils-9.11-manual",
                "gawk-5.4-manual",
                "grep-3.12-manual",
                "make-4.4.1-manual",
                "sed-manual-20260422",
                "tar-manual-20260611",
                "findutils-manual-20260714",
                "diffutils-3.12-manual",
                "glibc-2.44-manual",
                "gzip-1.14-manual",
                "wget-1.25-manual",
                "grub-2.14-manual",
            }.issubset(dataset_ids)
        )
        self.assertTrue(
            {
                "networkengineering-stackexchange",
                "dba-stackexchange",
                "electronics-stackexchange",
                "unix-stackexchange",
                "serverfault-stackexchange",
            }.issubset(dataset_ids)
        )
        self.assertTrue(
            {
                "softwareengineering-stackexchange",
                "cs-stackexchange",
                "arduino-stackexchange",
                "raspberrypi-stackexchange",
                "dsp-stackexchange",
                "superuser-stackexchange",
                "askubuntu-stackexchange",
            }.issubset(dataset_ids)
        )
        summary = storage_summary(datasets)
        self.assertLess(summary["download_max_bytes"], 9_000_000_000)
        self.assertLess(summary["indexed_max_bytes"], 120_000_000_000)

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

    def test_publisher_checksum_algorithm_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "datasets.json"
            template = {
                "dataset_id": "sqlite",
                "name": "SQLite",
                "description": "SQLite documentation",
                "category": "docs",
                "official_source_url": "https://sqlite.org/docs.html",
                "license": "Public domain",
                "attribution": "SQLite authors",
                "release": "1",
                "update_frequency": "release",
                "scope": "all",
                "formats": ["HTML"],
                "acquisition": {
                    "method": "http",
                    "location": "https://sqlite.org/docs.zip",
                    "publisher_checksum_algorithm": "sha3-256",
                    "publisher_checksum": "a" * 64,
                },
                "storage": {
                    "download_min_bytes": 1,
                    "download_max_bytes": 2,
                    "extracted_max_bytes": 3,
                    "indexed_max_bytes": 4,
                },
                "paths": {"raw": "raw/sqlite", "processed": "processed/sqlite", "index": "index/sqlite"},
                "status": "planned",
                "notes": "",
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [template]}))
            dataset = load_registry(registry)[0]
            self.assertEqual(dataset.acquisition["publisher_checksum_algorithm"], "sha3-256")

            invalid = {**template, "acquisition": {**template["acquisition"], "publisher_checksum_algorithm": "md5"}}
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [invalid]}))
            with self.assertRaisesRegex(ValueError, "unsupported publisher checksum algorithm"):
                load_registry(registry)

            invalid_type = {
                **template,
                "acquisition": {**template["acquisition"], "publisher_checksum_algorithm": ["sha3-256"]},
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [invalid_type]}))
            with self.assertRaisesRegex(ValueError, "unsupported publisher checksum algorithm"):
                load_registry(registry)

            missing = {
                **template,
                "acquisition": {
                    "method": "http",
                    "location": "https://sqlite.org/docs.zip",
                    "publisher_checksum_algorithm": "sha3-256",
                },
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [missing]}))
            with self.assertRaisesRegex(ValueError, "without a checksum"):
                load_registry(registry)

    def test_http_file_set_assets_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "datasets.json"
            template = {
                "dataset_id": "manual-set",
                "name": "Manual set",
                "description": "Official manuals",
                "category": "docs",
                "official_source_url": "https://example.invalid/docs/",
                "license": "test",
                "attribution": "test",
                "release": "1",
                "update_frequency": "release",
                "scope": "all",
                "formats": ["HTML"],
                "acquisition": {
                    "method": "http-file-set",
                    "location": "https://example.invalid/docs/",
                    "assets": [{"url": "https://example.invalid/docs/a.html", "filename": "a.html", "min_bytes": 1, "max_bytes": 10}],
                },
                "storage": {"download_min_bytes": 1, "download_max_bytes": 10, "extracted_max_bytes": 10, "indexed_max_bytes": 20},
                "paths": {"raw": "raw/manuals", "processed": "processed/manuals", "index": "indexes/manuals.sqlite3"},
                "status": "planned",
                "notes": "",
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [template]}), encoding="utf-8")
            self.assertEqual(load_registry(registry)[0].acquisition["assets"][0]["filename"], "a.html")
            invalid = {**template, "acquisition": {**template["acquisition"], "assets": [{"url": "https://example.invalid/a", "filename": "../a", "min_bytes": 1, "max_bytes": 2}]}}
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [invalid]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "filename must be a basename"):
                load_registry(registry)


if __name__ == "__main__":
    unittest.main()
