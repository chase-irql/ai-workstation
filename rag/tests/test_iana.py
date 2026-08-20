from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index, search
from offline_rag.iana import import_iana_registries
from offline_rag.retrieval import retrieve_document
from offline_rag.verify import verify_database


IANA_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<registry xmlns="http://www.iana.org/assignments" id="service-names-port-numbers">
  <title>Service Name and Transport Protocol Port Number Registry</title>
  <updated>2026-08-17</updated>
  <xref type="rfc" data="rfc6335"/>
  <registry id="service-names-port-numbers-1">
    <title>Service Names and Port Numbers</title>
    <registration_rule>IETF Review</registration_rule>
    <note>Ports identify services defined by <xref type="rfc" data="rfc6335"/>.</note>
    <record date="2026-01-01">
      <name>https</name>
      <number>443</number>
      <protocol>tcp</protocol>
      <description>HTTP over TLS</description>
      <xref type="rfc" data="rfc9110"/>
    </record>
    <record>
      <name>domain</name>
      <number>53</number>
      <protocol>udp</protocol>
      <description>Domain Name Server</description>
      <xref type="rfc" data="rfc1035"/>
    </record>
  </registry>
</registry>
"""


class IANAImporterTests(unittest.TestCase):
    def source(self, root: Path) -> Path:
        source = root / "source"
        registry = source / "service-names-port-numbers"
        registry.mkdir(parents=True)
        (registry / "service-names-port-numbers.xml").write_text(IANA_FIXTURE, encoding="utf-8")
        (source / "redirect.xml").write_text('<redirect xmlns="http://www.iana.org/assignments"/>', encoding="utf-8")
        (source / "templates").mkdir()
        (source / "templates" / "broken.xml").write_text("not xml", encoding="utf-8")
        return source

    def test_table_structure_metadata_search_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            output = root / "processed"
            result = import_iana_registries(
                source,
                output,
                source_version="snapshot-test",
                license_name="IANA terms",
                require_snapshot_manifest=False,
                max_chars=512,
            )
            self.assertEqual(result["registry_files"], 1)
            self.assertEqual(result["records"], 2)
            self.assertEqual(result["skipped_non_registry_xml"], 1)
            self.assertEqual(result["skipped_invalid_noncanonical_xml"], 1)

            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text().splitlines()]
            ports = next(item for item in documents if item["attributes"]["registry_id"].endswith("-1"))
            self.assertEqual(ports["source_timestamp"], "2026-08-17")
            self.assertEqual(ports["attributes"]["record_count"], 2)
            self.assertTrue(ports["source_url"].endswith(".xhtml#service-names-port-numbers-1"))
            https = next(item for item in chunks if item["attributes"].get("fields", {}).get("name") == "https")
            self.assertEqual(https["attributes"]["fields"]["number"], "443")
            self.assertEqual(https["attributes"]["references"], ["RFC 9110"])
            self.assertEqual(
                https["heading_path"],
                ["Service Name and Transport Protocol Port Number Registry", "Service Names and Port Numbers"],
            )

            database = root / "iana.sqlite3"
            build_index(output, database)
            top = search(database, "https 443 tcp", limit=1)[0]
            self.assertEqual(top["document_id"], ports["document_id"])
            self.assertIn("HTTP over TLS", top["text"])
            self.assertIn("iana", top["citation"].casefold())
            page = retrieve_document(database, ports["document_id"], chunk_limit=10)
            self.assertTrue(any(chunk["attributes"].get("fields", {}).get("number") == "53" for chunk in page["chunks"]))
            self.assertTrue(verify_database(database, output, smoke_queries=("https 443 tcp",))["verified"])

    def test_snapshot_required_and_existing_output_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            with self.assertRaisesRegex(ValueError, "Snapshot manifests"):
                import_iana_registries(
                    source,
                    root / "missing-manifest",
                    source_version="snapshot-test",
                    license_name="test",
                )
            output = root / "processed"
            import_iana_registries(
                source,
                output,
                source_version="snapshot-test",
                license_name="test",
                require_snapshot_manifest=False,
            )
            before = (output / "corpus-manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                import_iana_registries(
                    source,
                    output,
                    source_version="snapshot-test",
                    license_name="test",
                    require_snapshot_manifest=False,
                )
            self.assertEqual((output / "corpus-manifest.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
