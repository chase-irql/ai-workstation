from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.embeddings import EmbeddingModelConfig, OllamaEmbeddingClient


class EmbeddingClientTests(unittest.TestCase):
    def test_transient_runner_tokenizer_failure_is_retried(self):
        config = EmbeddingModelConfig("fixture", "fixture:latest", 2, None)
        client = OllamaEmbeddingClient(config, max_retries=1, retry_backoff_seconds=0)
        failure = HTTPError(
            "http://127.0.0.1:11434/api/embed",
            400,
            "Bad Request",
            None,
            io.BytesIO(b'{"error":"tokenize dial tcp: actively refused /tokenize"}'),
        )
        success = io.BytesIO(b'{"embeddings":[[3.0,4.0]]}')
        with patch("offline_rag.embeddings.urlopen", side_effect=[failure, success]) as mocked:
            vector = client.embed_query("test")
        self.assertEqual(mocked.call_count, 2)
        self.assertAlmostEqual(float(vector[0]), 0.6, places=6)
        self.assertAlmostEqual(float(vector[1]), 0.8, places=6)

    def test_nonretryable_bad_request_fails_immediately(self):
        config = EmbeddingModelConfig("fixture", "fixture:latest", 2, None)
        client = OllamaEmbeddingClient(config, max_retries=3, retry_backoff_seconds=0)
        failure = HTTPError(
            "http://127.0.0.1:11434/api/embed",
            400,
            "Bad Request",
            None,
            io.BytesIO(b'{"error":"invalid model input"}'),
        )
        with patch("offline_rag.embeddings.urlopen", side_effect=failure) as mocked:
            with self.assertRaisesRegex(RuntimeError, "after 1 attempt"):
                client.embed_query("test")
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
