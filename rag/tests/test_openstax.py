from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.openstax import import_openstax, parse_cnxml, parse_collection


COLLECTION = """<col:collection xmlns:col='http://cnx.rice.edu/collxml' xmlns:md='http://cnx.rice.edu/mdml'>
<col:metadata><md:title>Test Calculus</md:title><md:slug>test-calculus</md:slug>
<md:license>CC BY-NC-SA 4.0</md:license></col:metadata><col:content>
<col:module document='m1'/><col:subcollection><md:title>Limits</md:title><col:content>
<col:module document='m2'/></col:content></col:subcollection></col:content></col:collection>"""


MODULE = """<document xmlns='http://cnx.rice.edu/cnxml' xmlns:md='http://cnx.rice.edu/mdml'
xmlns:m='http://www.w3.org/1998/Math/MathML'><title>Limit Laws</title>
<metadata><md:content-id>m2</md:content-id><md:uuid>uuid-2</md:uuid></metadata><content>
<section><title>The Squeeze Theorem</title><para>A function is trapped between two others.</para>
<example><title>Compute a limit</title><para>Evaluate <m:math><m:mfrac><m:mi>x</m:mi><m:mn>2</m:mn></m:mfrac></m:math>.</para></example>
<exercise><problem><para>Find the limit.</para></problem><solution><para>The answer is 1.</para></solution></exercise>
<figure><media alt='Graph of three functions'/><caption>The middle graph is squeezed.</caption></figure>
</section></content></document>"""


class OpenStaxTests(unittest.TestCase):
    def test_collection_preserves_book_chapter_and_module_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.collection.xml"
            path.write_text(COLLECTION, encoding="utf-8")
            items = parse_collection(path, 2)
        self.assertEqual([item.module_id for item in items], ["m1", "m2"])
        self.assertEqual(items[1].hierarchy, ("Limits",))
        self.assertEqual(items[1].book_ordinal, 2)

    def test_cnxml_preserves_math_examples_solutions_and_captions(self):
        title, blocks, metadata = parse_cnxml(MODULE, "fallback")
        self.assertEqual(title, "Limit Laws")
        self.assertEqual(metadata["uuid"], "uuid-2")
        self.assertTrue(any("(x)/(2)" in block.text for block in blocks))
        self.assertTrue(any(block.heading_path[-1:] == ("Solution",) and "answer" in block.text for block in blocks))
        self.assertTrue(any(block.kind == "figure_caption" and "squeezed" in block.text for block in blocks))

    def test_top_level_media_alt_text_is_searchable(self):
        module = """<document xmlns='http://cnx.rice.edu/cnxml'><title>Appendix</title><content>
        <media id='periodic' alt='Periodic table with atomic numbers and element symbols'>
        <image src='periodic.jpg'/></media></content></document>"""
        _, blocks, _ = parse_cnxml(module, "fallback")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].kind, "figure_alt")
        self.assertIn("atomic numbers", blocks[0].text)

    def test_import_is_atomic_structured_and_protects_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "collections").mkdir()
            (root / "collections" / "test.collection.xml").write_text(COLLECTION, encoding="utf-8")
            for module_id in ("m1", "m2"):
                module = root / "modules" / module_id
                module.mkdir(parents=True)
                (module / "index.cnxml").write_text(MODULE.replace("m2", module_id), encoding="utf-8")
            output = root / "processed"
            result = import_openstax(
                root,
                output,
                corpus="openstax-test",
                source_version="fixture-v1",
                source_url_template="https://example.invalid/{relative_path}",
            )
            self.assertEqual(result["documents"], 2)
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(documents[1]["document_id"], "openstax-test:m2")
            self.assertEqual(documents[1]["attributes"]["chapter_path"], ["Limits"])
            self.assertTrue(chunks[0]["heading_path"][0] == "Test Calculus")
            with self.assertRaises(FileExistsError):
                import_openstax(
                    root,
                    output,
                    corpus="openstax-test",
                    source_version="fixture-v1",
                    source_url_template="https://example.invalid/{relative_path}",
                )

    def test_shared_modules_are_deduplicated_but_retain_occurrences(self):
        second_collection = COLLECTION.replace("Test Calculus", "Test Calculus II").replace(
            "test-calculus", "test-calculus-ii"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "collections").mkdir()
            (root / "collections" / "volume-1.collection.xml").write_text(COLLECTION, encoding="utf-8")
            (root / "collections" / "volume-2.collection.xml").write_text(second_collection, encoding="utf-8")
            for module_id in ("m1", "m2"):
                module = root / "modules" / module_id
                module.mkdir(parents=True)
                (module / "index.cnxml").write_text(MODULE.replace("m2", module_id), encoding="utf-8")
            output = root / "processed"
            result = import_openstax(
                root,
                output,
                corpus="openstax-test",
                source_version="fixture-v1",
                source_url_template="https://example.invalid/{relative_path}",
            )
            documents = [
                json.loads(line)
                for line in (output / "documents.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(result["documents"], 2)
        self.assertEqual(len(documents[0]["attributes"]["book_occurrences"]), 2)


if __name__ == "__main__":
    unittest.main()
