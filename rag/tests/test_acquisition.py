from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.acquisition import _download_http, extract_archive, validate_extraction
from offline_rag.dataset_registry import DatasetDefinition


class AcquisitionTests(unittest.TestCase):
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
