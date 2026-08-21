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
        self.assertGreaterEqual(len(datasets), 107)
        dataset_ids = {dataset.dataset_id for dataset in datasets}
        self.assertIn("devops-stackexchange", dataset_ids)
        self.assertIn("security-stackexchange", dataset_ids)
        self.assertIn("bash-5.3-manual", dataset_ids)
        self.assertIn("faa-amt-general-2023", dataset_ids)
        self.assertIn("doe-fundamentals-handbooks", dataset_ids)
        self.assertIn("faa-amt-airframe-powerplant-2023", dataset_ids)
        self.assertIn("hesperian-english-health-guides-20260820", dataset_ids)
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
        self.assertIn("dotnet-docs-20260820", dataset_ids)
        self.assertIn("nginx-docs-20260820", dataset_ids)
        self.assertIn("openstax-calculus", dataset_ids)
        self.assertIn("openstax-university-physics", dataset_ids)
        self.assertIn("openstax-chemistry", dataset_ids)
        self.assertIn("openstax-biology", dataset_ids)
        self.assertIn("openstax-anatomy-physiology", dataset_ids)
        self.assertIn("openstax-foundational-algebra", dataset_ids)
        self.assertIn("openstax-college-algebra", dataset_ids)
        self.assertIn("openstax-introductory-statistics", dataset_ids)
        self.assertIn("openstax-microbiology", dataset_ids)
        self.assertIn("openstax-astronomy", dataset_ids)
        self.assertIn("openstax-principles-economics", dataset_ids)
        self.assertIn("openstax-psychology", dataset_ids)
        self.assertIn("ifixit-english-2025-12", dataset_ids)
        self.assertIn("swiftui-docs-20260820", dataset_ids)
        self.assertIn("pubmed-baseline-2026", dataset_ids)
        self.assertTrue(
            {
                "react-docs-20260820",
                "nextjs-docs-20260820",
                "vue-docs-20260820",
                "angular-docs-20260820",
                "django-docs-20260820",
                "fastapi-docs-20260820",
                "flask-docs-20260820",
                "spring-boot-docs-20260820",
                "aspnetcore-docs-20260820",
                "laravel-docs-13",
                "rails-guides-20260820",
                "ktor-docs-20260820",
            }.issubset(dataset_ids)
        )
        self.assertTrue(
            {
                "windows-server-docs-20260820",
                "powershell-docs-20260820",
                "wsl-docs-20260820",
                "win32-docs-20260820",
                "sysinternals-docs-20260820",
            }.issubset(dataset_ids)
        )
        self.assertTrue(
            {
                "gradle-docs-20260820",
                "maven-docs-20260820",
                "npm-docs-20260820",
                "pnpm-docs-20260820",
                "yarn-berry-docs-20260820",
                "composer-docs-20260820",
                "bundler-docs-20260820",
                "swiftpm-docs-20260820",
            }.issubset(dataset_ids)
        )
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
        self.assertLess(summary["download_max_bytes"], 650_000_000_000)
        self.assertLess(summary["indexed_max_bytes"], 650_000_000_000)

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

            invalid = {**template, "acquisition": {**template["acquisition"], "publisher_checksum_algorithm": "sha1"}}
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

    def test_http_catalog_file_set_constraints_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "datasets.json"
            template = {
                "dataset_id": "catalog-set",
                "name": "Catalog set",
                "description": "Official linked files",
                "category": "docs",
                "official_source_url": "https://example.invalid/catalog",
                "license": "test",
                "attribution": "test",
                "release": "1",
                "update_frequency": "release",
                "scope": "all",
                "formats": ["PDF"],
                "acquisition": {
                    "method": "http-catalog-file-set",
                    "location": "https://example.invalid/catalog",
                    "asset_url_prefix": "https://example.invalid/files/",
                    "asset_path_pattern": r"^book/[^/]+\.pdf$",
                    "min_assets": 1,
                    "max_assets": 10,
                    "asset_min_bytes": 5,
                    "asset_max_bytes": 100,
                    "asset_magic": "%PDF-",
                    "max_concurrency": 4,
                    "excluded_relative_paths": ["book/broken.pdf"],
                    "collection_titles": {"book": "Book"},
                },
                "storage": {
                    "download_min_bytes": 5,
                    "download_max_bytes": 1000,
                    "extracted_max_bytes": 1000,
                    "indexed_max_bytes": 2000,
                },
                "paths": {
                    "raw": "raw/catalog",
                    "processed": "processed/catalog",
                    "index": "indexes/catalog.sqlite3",
                },
                "status": "planned",
                "notes": "",
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [template]}), encoding="utf-8")
            self.assertEqual(load_registry(registry)[0].acquisition["max_concurrency"], 4)

            invalid = {
                **template,
                "acquisition": {
                    **template["acquisition"],
                    "excluded_relative_paths": ["../escape.pdf"],
                },
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [invalid]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe or duplicate exclusion"):
                load_registry(registry)

    def test_http_site_mirror_constraints_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "datasets.json"
            template = {
                "dataset_id": "site-mirror",
                "name": "Site mirror",
                "description": "Versioned documentation site",
                "category": "docs",
                "official_source_url": "https://docs.example.invalid/v1/",
                "license": "test",
                "attribution": "test",
                "release": "1",
                "update_frequency": "release",
                "scope": "all HTML",
                "formats": ["HTML"],
                "acquisition": {
                    "method": "http-site-mirror",
                    "location": "https://docs.example.invalid/v1/",
                    "allowed_prefix": "https://docs.example.invalid/v1/",
                    "max_files": 100,
                    "max_bytes": 1000000,
                    "max_concurrency": 4,
                },
                "storage": {
                    "download_min_bytes": 1,
                    "download_max_bytes": 1000000,
                    "extracted_max_bytes": 1000000,
                    "indexed_max_bytes": 2000000,
                },
                "paths": {
                    "raw": "raw/site",
                    "processed": "processed/site",
                    "index": "indexes/site.sqlite3",
                },
                "status": "planned",
                "notes": "",
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [template]}), encoding="utf-8")
            self.assertEqual(load_registry(registry)[0].acquisition["method"], "http-site-mirror")

            invalid = {**template, "acquisition": {**template["acquisition"], "max_concurrency": 17}}
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [invalid]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not exceed 16"):
                load_registry(registry)


if __name__ == "__main__":
    unittest.main()
