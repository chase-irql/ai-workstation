from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.acquisition import _download_http, acquire_dataset, extract_archive, validate_extraction
from offline_rag.dataset_registry import DatasetDefinition
import py7zr


class AcquisitionTests(unittest.TestCase):
    def test_http_file_set_hashes_and_manifests_each_bounded_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "datasets.json"
            dataset = {
                "dataset_id": "manual-set",
                "name": "Manual set",
                "description": "Several official manuals",
                "category": "docs",
                "official_source_url": "https://example.invalid/docs/",
                "license": "test",
                "attribution": "test",
                "release": "1",
                "update_frequency": "release",
                "scope": "manuals",
                "formats": ["HTML"],
                "acquisition": {
                    "method": "http-file-set",
                    "location": "https://example.invalid/docs/",
                    "assets": [
                        {"url": "https://example.invalid/docs/a.html", "filename": "a.html", "min_bytes": 1, "max_bytes": 10},
                        {"url": "https://example.invalid/docs/b.html", "filename": "b.html", "min_bytes": 1, "max_bytes": 10}
                    ]
                },
                "storage": {"download_min_bytes": 2, "download_max_bytes": 20, "extracted_max_bytes": 20, "indexed_max_bytes": 100},
                "paths": {"raw": "raw/manuals", "processed": "processed/manuals", "index": "indexes/manuals.sqlite3"},
                "status": "planned",
                "notes": ""
            }
            registry.write_text(json.dumps({"schema_version": 1, "datasets": [dataset]}), encoding="utf-8")

            def fake_download(definition, destination):
                payload = destination.name.encode("ascii")
                destination.write_bytes(payload)
                return {"path": destination, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "reused": False, "publisher_checksum": None}

            with patch("offline_rag.acquisition._download_http", side_effect=fake_download):
                manifest = acquire_dataset(registry, "manual-set", root)
            self.assertEqual(manifest["status"], "validated")
            self.assertEqual(manifest["integrity"]["files_hashed"], 2)
            self.assertEqual([item["filename"] for item in manifest["files"]], ["a.html", "b.html"])
            self.assertTrue((root / "raw/manuals/acquisition-manifest.json").is_file())

    def test_http_download_resumes_a_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = (b"offline documentation archive\n" * 4096)

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    start = 0
                    range_header = self.headers.get("Range")
                    if range_header:
                        start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                        self.send_response(206)
                        self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                    else:
                        self.send_response(200)
                    self.send_header("Content-Length", str(len(payload) - start))
                    self.end_headers()
                    self.wfile.write(payload[start:])

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                dataset = DatasetDefinition(
                    dataset_id="fixture",
                    name="Fixture",
                    description="Fixture",
                    category="docs",
                    official_source_url="https://example.invalid",
                    license="test",
                    attribution="test",
                    release="1",
                    update_frequency="never",
                    scope="fixture",
                    formats=("binary",),
                    acquisition={"method": "http", "location": f"http://127.0.0.1:{server.server_port}/docs.bin"},
                    storage={
                        "download_min_bytes": len(payload),
                        "download_max_bytes": len(payload),
                        "extracted_max_bytes": len(payload),
                        "indexed_max_bytes": len(payload),
                    },
                    paths={"raw": "raw", "processed": "processed", "index": "index"},
                    status="planned",
                    notes="",
                )
                destination = root / "docs.bin"
                partial = destination.with_suffix(".bin.partial")
                partial.write_bytes(payload[:1000])
                result = _download_http(dataset, destination)
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(result["bytes"], len(payload))
                self.assertFalse(partial.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_download_publishes_complete_partial_when_server_ignores_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("docs/readme.txt", b"complete immutable archive\n" * 4096)
            payload = buffer.getvalue()

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    # Simulate codeload.github.com: Range may be ignored and
                    # the followed response may omit Content-Length.
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                dataset = DatasetDefinition(
                    dataset_id="complete-fixture",
                    name="Complete fixture",
                    description="Fixture",
                    category="docs",
                    official_source_url="https://example.invalid",
                    license="test",
                    attribution="test",
                    release="1",
                    update_frequency="never",
                    scope="fixture",
                    formats=("binary",),
                    acquisition={"method": "http", "location": f"http://127.0.0.1:{server.server_port}/docs.bin"},
                    storage={
                        "download_min_bytes": len(payload),
                        "download_max_bytes": len(payload),
                        "extracted_max_bytes": len(payload),
                        "indexed_max_bytes": len(payload),
                    },
                    paths={"raw": "raw", "processed": "processed", "index": "index"},
                    status="planned",
                    notes="",
                )
                destination = root / "docs.bin"
                partial = destination.with_suffix(".bin.partial")
                partial.write_bytes(payload)
                result = _download_http(dataset, destination)
                self.assertEqual(destination.read_bytes(), payload)
                self.assertTrue(result["reused"])
                self.assertFalse(partial.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_download_verifies_publisher_sha3_256(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"official sqlite documentation fixture\n" * 1024

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                expected = hashlib.sha3_256(payload).hexdigest()
                dataset = DatasetDefinition(
                    dataset_id="sqlite-fixture",
                    name="SQLite fixture",
                    description="Fixture",
                    category="docs",
                    official_source_url="https://example.invalid",
                    license="test",
                    attribution="test",
                    release="1",
                    update_frequency="never",
                    scope="fixture",
                    formats=("binary",),
                    acquisition={
                        "method": "http",
                        "location": f"http://127.0.0.1:{server.server_port}/docs.bin",
                        "publisher_checksum_algorithm": "sha3-256",
                        "publisher_checksum": expected,
                    },
                    storage={
                        "download_min_bytes": len(payload),
                        "download_max_bytes": len(payload),
                        "extracted_max_bytes": len(payload),
                        "indexed_max_bytes": len(payload),
                    },
                    paths={"raw": "raw", "processed": "processed", "index": "index"},
                    status="planned",
                    notes="",
                )
                result = _download_http(dataset, root / "docs.bin")
                self.assertEqual(result["publisher_checksum"]["algorithm"], "sha3-256")
                self.assertEqual(result["publisher_checksum"]["value"], expected)
                self.assertTrue(result["publisher_checksum"]["verified"])

                mismatch = DatasetDefinition(
                    **{
                        **dataset.__dict__,
                        "acquisition": {
                            **dataset.acquisition,
                            "publisher_checksum": "0" * 64,
                        },
                    }
                )
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    _download_http(mismatch, root / "docs.bin")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_zip_is_integrity_checked_and_atomically_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "docs.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("docs/index.html", "<h1>Documentation</h1>")
                bundle.writestr("docs/api/reference.md", "# Reference")
            output = root / "extracted"
            result = extract_archive(archive, output)
            self.assertEqual(result["files"], 2)
            self.assertTrue((output / "docs" / "index.html").is_file())
            validated = validate_extraction(archive, output)
            self.assertEqual(validated["files"], 2)
            with self.assertRaises(FileExistsError):
                extract_archive(archive, output)

    def test_7z_is_integrity_checked_and_atomically_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Posts.xml"
            source.write_text('<posts><row Id="1" /></posts>', encoding="utf-8")
            archive = root / "site.7z"
            with py7zr.SevenZipFile(archive, mode="w") as bundle:
                bundle.write(source, "Posts.xml")
            output = root / "extracted"
            result = extract_archive(archive, output)
            self.assertEqual(result["files"], 1)
            self.assertEqual((output / "Posts.xml").read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            self.assertEqual(validate_extraction(archive, output)["files"], 1)

    def test_7z_path_traversal_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("do not escape", encoding="utf-8")
            archive = root / "malicious.7z"
            with py7zr.SevenZipFile(archive, mode="w") as bundle:
                bundle.write(source, "../escape.txt")
            output = root / "extracted"
            with self.assertRaisesRegex(ValueError, "escapes"):
                extract_archive(archive, output)
            self.assertFalse(output.exists())
            self.assertFalse((root / "escape.txt").exists())

    def test_archive_path_traversal_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape.txt", "do not write")
            output = root / "extracted"
            with self.assertRaisesRegex(ValueError, "escapes"):
                extract_archive(archive, output)
            self.assertFalse(output.exists())
            self.assertFalse((root / "escape.txt").exists())

    def test_tar_skips_safe_internal_links_and_rejects_escaping_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "safe.tar"
            payload = b"release notes"
            with tarfile.open(archive, "w") as bundle:
                regular = tarfile.TarInfo("docs/release.txt")
                regular.size = len(payload)
                bundle.addfile(regular, io.BytesIO(payload))
                link = tarfile.TarInfo("docs/latest")
                link.type = tarfile.SYMTYPE
                link.linkname = "release.txt"
                bundle.addfile(link)
            output = root / "safe-output"
            result = extract_archive(archive, output)
            self.assertEqual(result["skipped_archive_links"], 1)
            self.assertEqual((output / "docs" / "release.txt").read_bytes(), payload)
            self.assertFalse((output / "docs" / "latest").exists())
            self.assertEqual(validate_extraction(archive, output)["skipped_archive_links"], 1)

            malicious = root / "malicious.tar"
            with tarfile.open(malicious, "w") as bundle:
                link = tarfile.TarInfo("docs/escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../escape.txt"
                bundle.addfile(link)
            with self.assertRaisesRegex(ValueError, "escapes"):
                extract_archive(malicious, root / "malicious-output")

    def test_tar_reversibly_encodes_ntfs_invalid_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unix-names.tar"
            payload = b"attribute manual"
            with tarfile.open(archive, "w") as bundle:
                regular = tarfile.TarInfo("man/man3attr/gnu::aligned.3attr")
                regular.size = len(payload)
                bundle.addfile(regular, io.BytesIO(payload))
            output = root / "output"
            result = extract_archive(archive, output)
            self.assertEqual(result["portable_encoded_members"], 1)
            self.assertTrue((output / "man" / "man3attr" / "gnu%3A%3Aaligned.3attr").is_file())
            self.assertTrue((output / ".archive-name-encoding-v1.json").is_file())
            self.assertEqual(validate_extraction(archive, output)["portable_encoded_members"], 1)

    def test_tar_preserves_case_distinct_unix_names_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "case-sensitive.tar"
            with tarfile.open(archive, "w") as bundle:
                for name, payload in (("man/_Exit.2", b"uppercase"), ("man/_exit.2", b"lowercase")):
                    regular = tarfile.TarInfo(name)
                    regular.size = len(payload)
                    bundle.addfile(regular, io.BytesIO(payload))
            output = root / "output"
            extract_archive(archive, output)
            self.assertEqual((output / "man" / "_%45xit.2").read_bytes(), b"uppercase")
            self.assertEqual((output / "man" / "_exit.2").read_bytes(), b"lowercase")
            validate_extraction(archive, output)


if __name__ == "__main__":
    unittest.main()
