from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from offline_rag.site_mirror import mirror_site


class _Handler(BaseHTTPRequestHandler):
    pages = {
        "/docs/": b'<html><body><h1>Root</h1><a href="a.html">A</a><a href="/outside.html">outside</a></body></html>',
        "/docs/a.html": b'<html><body><h1>A</h1><a href="sub/">Sub</a><a href="missing.html">missing</a><a href="#same">same</a></body></html>',
        "/docs/sub/": b"<html><body><h1>Sub</h1></body></html>",
    }

    def do_GET(self) -> None:  # noqa: N802
        body = self.pages.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


class SiteMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/docs/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_resumes_and_publishes_atomically(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "mirror"
            with self.assertRaises(InterruptedError):
                mirror_site(
                    location=self.base_url,
                    allowed_prefix=self.base_url,
                    output=output,
                    max_files=10,
                    max_bytes=100_000,
                    max_concurrency=2,
                    stop_after=1,
                )
            self.assertFalse(output.exists())
            self.assertTrue(output.with_name(".mirror.site-partial").is_dir())

            manifest = mirror_site(
                location=self.base_url,
                allowed_prefix=self.base_url,
                output=output,
                max_files=10,
                max_bytes=100_000,
                max_concurrency=2,
            )
            self.assertTrue(manifest["completed"])
            self.assertEqual(manifest["document_count"], 3)
            self.assertEqual(manifest["skipped_count"], 1)
            self.assertTrue((output / "extracted" / "index.html").is_file())
            self.assertTrue((output / "extracted" / "a.html").is_file())
            self.assertTrue((output / "extracted" / "sub" / "index.html").is_file())
            persisted = json.loads((output / "site-acquisition-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["aggregate_sha256"], manifest["aggregate_sha256"])

    def test_rejects_unrecognized_existing_output(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "mirror"
            output.mkdir()
            unrelated = output / "unrelated.txt"
            unrelated.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                mirror_site(
                    location=self.base_url,
                    allowed_prefix=self.base_url,
                    output=output,
                    max_files=10,
                    max_bytes=100_000,
                    max_concurrency=1,
                )
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_failed_forced_rebuild_preserves_published_mirror(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "mirror"
            output.mkdir()
            (output / "site-acquisition-manifest.json").write_text(
                json.dumps({"schema_version": 1, "completed": True}), encoding="utf-8"
            )
            marker = output / "accepted.html"
            marker.write_text("accepted", encoding="utf-8")

            with patch("offline_rag.site_mirror._fetch_page", side_effect=RuntimeError("synthetic failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    mirror_site(
                        location=self.base_url,
                        allowed_prefix=self.base_url,
                        output=output,
                        max_files=10,
                        max_bytes=100_000,
                        max_concurrency=1,
                        force=True,
                    )

            self.assertEqual(marker.read_text(encoding="utf-8"), "accepted")

    def test_successful_forced_rebuild_replaces_only_published_mirror(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "mirror"
            output.mkdir()
            (output / "site-acquisition-manifest.json").write_text(
                json.dumps({"schema_version": 1, "completed": True}), encoding="utf-8"
            )
            (output / "old.html").write_text("old", encoding="utf-8")

            manifest = mirror_site(
                location=self.base_url,
                allowed_prefix=self.base_url,
                output=output,
                max_files=10,
                max_bytes=100_000,
                max_concurrency=2,
                force=True,
            )

            self.assertEqual(manifest["document_count"], 3)
            self.assertFalse((output / "old.html").exists())
            self.assertTrue((output / "extracted" / "index.html").is_file())
            self.assertEqual(list(Path(directory).glob(".mirror.*.previous")), [])


if __name__ == "__main__":
    unittest.main()
