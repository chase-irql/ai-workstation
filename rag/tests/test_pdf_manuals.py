from __future__ import annotations

import base64
import io
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index, search
from offline_rag.pdf_manuals import _extract_page_text, _page_content_blocks, import_pdf_manuals
from offline_rag.retrieval import search_documents
from offline_rag.verify import verify_database


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_text_manual(path: Path) -> None:
    pdf = canvas.Canvas(str(path))
    pdf.setTitle("Pump Controller Service Manual")
    pdf.setAuthor("Example Manufacturer")
    pdf.bookmarkPage("troubleshooting")
    pdf.addOutlineEntry("Troubleshooting", "troubleshooting", level=0)
    pdf.drawString(72, 740, "Error E23 means that the intake filter is blocked.")
    pdf.drawString(72, 720, "Disconnect power and clean the intake filter before restart.")
    pdf.showPage()
    pdf.bookmarkPage("calibration")
    pdf.addOutlineEntry("Calibration", "calibration", level=0)
    text = pdf.beginText(72, 740)
    text.textLine("Calibration procedure")
    for index in range(35):
        text.textLine(f"Step {index + 1}: adjust sensor gain and verify the reference voltage.")
    pdf.drawText(text)
    pdf.showPage()
    pdf.showPage()
    pdf.save()


def _write_mixed_scan(path: Path) -> None:
    pdf = canvas.Canvas(str(path))
    pdf.setTitle("Partially Scanned Manual")
    pdf.drawImage(ImageReader(io.BytesIO(ONE_PIXEL_PNG)), 72, 600, width=200, height=100)
    pdf.showPage()
    pdf.drawString(72, 740, "This page has a searchable text layer.")
    pdf.showPage()
    pdf.save()


def _write_rehydration_methods(path: Path) -> None:
    pdf = canvas.Canvas(str(path))
    text = pdf.beginText(72, 740)
    for line in (
        "2 ways to make rehydration drink",
        "With sugar and salt",
        "In 1 liter of clean water, mix:",
        "half a level teaspoon of salt",
        "8 level teaspoons of sugar",
        "With powdered cereal and salt",
        "In 1 liter of clean water, mix:",
        "half a level teaspoon of salt",
        "8 heaping teaspoons of powdered cereal",
        "Boil for 5 to 7 minutes to form a watery porridge.",
        "If possible, add half a cup of fruit juice to either drink.",
        "Give frequent small sips and seek help if danger signs appear.",
    ):
        text.textLine(line)
    pdf.drawText(text)
    pdf.save()


class PdfManualImportTests(unittest.TestCase):
    def test_hesperian_procedure_sectioning_keeps_alternative_steps_separate(self):
        text = """2 ways to make rehydration drink
With sugar and salt
In 1 liter of clean water, mix:
half a level teaspoon of salt
8 level teaspoons of sugar
With powdered cereal and salt
In 1 liter of clean water, mix:
half a level teaspoon of salt
8 heaping teaspoons of powdered cereal
Boil for 5 to 7 minutes to form a watery porridge.
If possible, add half a cup of fruit juice to either drink.
Give frequent small sips and seek help if danger signs appear.
"""
        blocks = _page_content_blocks(
            ("Page 7",),
            text,
            {"page_number": 7, "page_label": "7"},
            "hesperian-procedures",
        )
        by_heading = {block.heading_path[-1]: block for block in blocks}
        sugar = by_heading["With sugar and salt"]
        cereal = by_heading["With powdered cereal and salt"]
        shared = by_heading["Shared procedure instructions"]
        self.assertNotIn("boil", sugar.text.casefold())
        self.assertNotIn("cereal", sugar.text.casefold())
        self.assertIn("boil", cereal.text.casefold())
        self.assertNotIn("level teaspoons of sugar", cereal.text.casefold())
        self.assertIn("either drink", shared.text.casefold())
        self.assertTrue(sugar.attributes["derived_evidence"])
        self.assertIn("Rehydration drink", sugar.heading_path)
        self.assertEqual(sugar.attributes["evidence_kind"], "procedure_method")
        self.assertEqual(shared.attributes["evidence_kind"], "procedure_shared")

    def test_hesperian_sectioning_rejects_interleaved_recipe_columns(self):
        text = """2 WAYS TO MAKE HOME MIX REHYDRATION DRINK
1. WITH SUGAR AND SALT
2. WITH POWDERED CEREAL AND SALT
In 1 liter of water put half a teaspoon of salt and 8 heaping teaspoons of powdered cereal.
In 1 liter of water put half a teaspoon of salt and 8 level
teaspoons of sugar.
Boil for 5 to 7 minutes.
"""
        blocks = _page_content_blocks(("Page 152",), text, {"page_number": 2}, "hesperian-procedures")
        self.assertEqual([block.kind for block in blocks], ["pdf-page"])

    def test_document_retrieval_prefers_method_specific_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "methods.pdf"
            _write_rehydration_methods(manual)
            output = root / "processed"
            import_pdf_manuals(
                manual,
                output,
                corpus="health-guides",
                source_version="1",
                license_name="test",
                sectioning_profile="hesperian-procedures",
                extraction_mode="plain",
            )
            database = root / "methods.sqlite3"
            build_index(output, database)

            sugar = search_documents(
                database,
                "rehydration drink",
                limit=1,
                allow_relaxation=False,
            )["results"][0]
            self.assertEqual(sugar["evidence_kind"], "procedure_method")
            self.assertEqual(sugar["procedure_method"], "With sugar and salt")
            self.assertNotIn("boil", sugar["text"].casefold())
            self.assertNotIn("cereal", sugar["text"].casefold())

            cereal = search_documents(
                database,
                "rehydration drink powdered cereal salt boil",
                limit=1,
                allow_relaxation=False,
            )["results"][0]
            self.assertEqual(cereal["procedure_method"], "With powdered cereal and salt")
            self.assertNotIn("sugar", cereal["text"].casefold())

    def test_pypdf_page_warnings_are_collected_without_changing_text(self):
        class WarningPage:
            def extract_text(self, **_: object) -> str:
                logger = logging.getLogger("pypdf.test")
                logger.warning("PDF contains an uninterpretable font. Output will be incomplete.")
                logger.warning("Rotated text discovered. Layout will be degraded.")
                return "  searchable   text  "

        text, warnings = _extract_page_text(WarningPage())
        self.assertEqual(text, "searchable   text")
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("uninterpretable font" in warning for warning in warnings))
        self.assertTrue(any("Rotated text" in warning for warning in warnings))

    def test_plain_mode_uses_content_stream_order_for_multicolumn_pages(self):
        class TwoColumnPage:
            calls: list[dict[str, object]] = []

            def extract_text(self, **kwargs: object) -> str:
                self.calls.append(kwargs)
                if kwargs.get("extraction_mode") == "layout":
                    return "half teaspoon SUGAR eight teaspoons SALT"
                return "half teaspoon SALT\neight teaspoons SUGAR"

        page = TwoColumnPage()
        layout_text, _ = _extract_page_text(page, "layout")
        plain_text, _ = _extract_page_text(page, "plain")
        self.assertEqual(layout_text, "half teaspoon SUGAR eight teaspoons SALT")
        self.assertEqual(plain_text, "half teaspoon SALT\neight teaspoons SUGAR")
        self.assertEqual(page.calls[1], {})

        with self.assertRaisesRegex(ValueError, "layout.*plain"):
            _extract_page_text(page, "columns")  # type: ignore[arg-type]

    def test_page_aware_common_records_bm25_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            manual = source / "pump-controller.pdf"
            _write_text_manual(manual)
            output = root / "processed"
            result = import_pdf_manuals(
                source,
                output,
                corpus="pump-manuals",
                source_version="rev-2026-08",
                license_name="test fixture license",
                source_url_template="https://example.test/manuals/{relative_path}",
                source_timestamp="2026-08-20T00:00:00Z",
                max_chars=512,
                min_chars=60,
                title_overrides={"pump-controller.pdf": "Pump Controller Manual — Corrected Title"},
            )
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["pages"], 3)
            self.assertEqual(result["text_pages"], 2)
            self.assertEqual(result["blank_pages"], 1)
            self.assertEqual(result["pages_with_pypdf_warnings"], 0)

            manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
            stats = json.loads((output / "extraction-stats.json").read_text(encoding="utf-8"))
            document = json.loads((output / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(manifest["importer"], "pdf-manuals-v1")
            self.assertFalse(manifest["configuration"]["ocr"])
            self.assertEqual(manifest["configuration"]["text_extraction_mode"], "layout")
            self.assertTrue(stats["completed"])
            self.assertEqual(stats["stop_reason"], "source_complete")
            self.assertEqual(document["title"], "Pump Controller Manual — Corrected Title")
            self.assertEqual(document["attributes"]["pdf_title"], "Pump Controller Service Manual")
            self.assertTrue(document["attributes"]["title_overridden"])
            self.assertEqual(document["attributes"]["pdf_author"], "Example Manufacturer")
            self.assertEqual(document["attributes"]["page_count"], 3)
            self.assertEqual(document["attributes"]["pages_with_pypdf_warnings"], 0)
            self.assertEqual(document["source_url"], "https://example.test/manuals/pump-controller.pdf")
            self.assertTrue(all(chunk["attributes"]["page_number"] in {1, 2} for chunk in chunks))
            self.assertTrue(any("Page 1" in chunk["heading_path"] for chunk in chunks))
            self.assertTrue(any("Troubleshooting" in chunk["heading_path"] for chunk in chunks))
            self.assertTrue(all(len(chunk["text"]) <= 512 for chunk in chunks))
            self.assertEqual(chunks[0]["next_chunk_id"], chunks[1]["chunk_instance_id"])

            database = root / "manuals.sqlite3"
            build_index(output, database)
            verification = verify_database(database, output, smoke_queries=("E23 intake filter",))
            self.assertTrue(verification["verified"])
            found = search(database, "E23 intake filter", limit=3)[0]
            self.assertEqual(found["document_id"], document["document_id"])
            self.assertIn("Troubleshooting > Page 1", found["citation"])
            self.assertIn("pump-controller.pdf", found["source_url"])

    def test_low_searchable_ratio_requires_ocr_without_publishing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "mixed.pdf"
            _write_mixed_scan(manual)
            output = root / "processed"
            with self.assertRaisesRegex(ValueError, "OCR required"):
                import_pdf_manuals(
                    manual,
                    output,
                    corpus="scan-test",
                    source_version="1",
                    license_name="test",
                    min_searchable_ratio=0.75,
                )
            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".processed.building-*")))

    def test_existing_and_unrecognized_output_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "manual.pdf"
            _write_text_manual(manual)
            output = root / "processed"
            options = {"corpus": "manual-test", "source_version": "1", "license_name": "test"}
            import_pdf_manuals(manual, output, **options)
            before = (output / "corpus-manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                import_pdf_manuals(manual, output, **options)
            self.assertEqual((output / "corpus-manifest.json").read_bytes(), before)
            (output / "personal.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                import_pdf_manuals(manual, output, force=True, **options)
            self.assertEqual((output / "personal.txt").read_text(encoding="utf-8"), "preserve")

    def test_invalid_arguments_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "manual.pdf"
            _write_text_manual(manual)
            with self.assertRaisesRegex(ValueError, "between zero and one"):
                import_pdf_manuals(
                    manual,
                    root / "output",
                    corpus="manual-test",
                    source_version="1",
                    license_name="test",
                    min_searchable_ratio=1.1,
                )
            with self.assertRaisesRegex(ValueError, "relative_path"):
                import_pdf_manuals(
                    manual,
                    root / "output",
                    corpus="manual-test",
                    source_version="1",
                    license_name="test",
                    source_url_template="https://example.test/manual.pdf",
                )
            with self.assertRaisesRegex(ValueError, "do not match source PDFs"):
                import_pdf_manuals(
                    manual,
                    root / "output",
                    corpus="manual-test",
                    source_version="1",
                    license_name="test",
                    title_overrides={"missing.pdf": "Missing Manual"},
                )


if __name__ == "__main__":
    unittest.main()
