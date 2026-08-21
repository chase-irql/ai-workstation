from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.pubmed import import_pubmed
from offline_rag.bm25 import build_index, search


ARTICLE = """<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">12345</PMID>
    <DateRevised><Year>2026</Year><Month>01</Month><Day>15</Day></DateRevised>
    <Article>
      <Journal><ISSN>1234-5678</ISSN><JournalIssue><Volume>8</Volume><Issue>2</Issue><PubDate><Year>2025</Year><Month>Dec</Month></PubDate></JournalIssue><Title>Journal of Tests</Title><ISOAbbreviation>J Test</ISOAbbreviation></Journal>
      <ArticleTitle>Hydration &amp; recovery</ArticleTitle>
      <Pagination><MedlinePgn>10-18</MedlinePgn></Pagination>
      <Abstract><AbstractText Label="BACKGROUND">Why hydration matters.</AbstractText><AbstractText Label="METHODS">A measured intervention.</AbstractText></Abstract>
      <AuthorList><Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author></AuthorList>
      <Language>eng</Language>
      <PublicationTypeList><PublicationType>Clinical Trial</PublicationType></PublicationTypeList>
    </Article>
    <MeshHeadingList><MeshHeading><DescriptorName>Fluid Therapy</DescriptorName><QualifierName>methods</QualifierName></MeshHeading></MeshHeadingList>
    <KeywordList><Keyword>rehydration</Keyword></KeywordList>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pubmed">12345</ArticleId><ArticleId IdType="doi">10.1/example</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle>"""


def _write_source(root: Path, names: list[str]) -> None:
    files = root / "files"
    files.mkdir(parents=True)
    manifest_files = []
    for index, name in enumerate(names):
        payload = f"<PubmedArticleSet>{ARTICLE.replace('12345', str(12345 + index))}</PubmedArticleSet>".encode()
        path = files / name
        with gzip.open(path, "wb") as stream:
            stream.write(payload)
        manifest_files.append(
            {
                "filename": name,
                "relative_path": name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (root / "acquisition-manifest.json").write_text(
        json.dumps({"dataset_id": "pubmed-test", "status": "validated", "files": manifest_files}),
        encoding="utf-8",
    )


def _read_zstd_jsonl(path: Path) -> list[dict[str, object]]:
    with zstandard.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def test_pubmed_streaming_import_preserves_metadata_and_resumes_by_source_file() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "raw"
        output = root / "processed"
        _write_source(source, ["pubmed26n0001.xml.gz", "pubmed26n0002.xml.gz", "pubmed26n0003.xml.gz"])
        first = import_pubmed(
            source,
            output,
            corpus="pubmed-test",
            source_version="2026 baseline",
            license_text="NLM terms",
            max_files=1,
        )
        assert first["completed"] is False
        assert first["parts"] == 1
        assert not output.exists()

        result = import_pubmed(
            source,
            output,
            corpus="pubmed-test",
            source_version="2026 baseline",
            license_text="NLM terms",
            workers=2,
        )
        assert result["completed"] is True
        manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"] == {"documents": 3, "chunks": 9, "skipped_records": 0}
        assert len(manifest["parts"]) == 3
        documents = _read_zstd_jsonl(output / manifest["parts"][0]["documents"])
        chunks = _read_zstd_jsonl(output / manifest["parts"][0]["chunks"])
        assert documents[0]["document_id"] == "pubmed-test:pmid:12345"
        assert documents[0]["source_url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
        assert documents[0]["attributes"]["doi"] == "10.1/example"
        assert documents[0]["attributes"]["mesh_terms"] == ["Fluid Therapy / methods"]
        assert {chunk["heading_path"][0] for chunk in chunks} == {"Abstract", "Indexing"}
        assert all(chunk["document_id"] == documents[0]["document_id"] for chunk in chunks)
        database = root / "pubmed.sqlite3"
        built = build_index(output, database)
        assert built["documents"] == 3
        results = search(database, "fluid therapy methods", limit=5)
        assert results[0]["document_id"] == "pubmed-test:pmid:12345"
        assert results[0]["source_url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
        assert "pubmed-test" in results[0]["citation"]


def test_pubmed_rejects_unvalidated_source_and_existing_output() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "raw"
        output = root / "processed"
        _write_source(source, ["pubmed26n0001.xml.gz"])
        manifest_path = source / "acquisition-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "partial"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError, match="validated"):
            import_pubmed(
                source,
                output,
                corpus="pubmed-test",
                source_version="2026 baseline",
                license_text="NLM terms",
            )

        manifest["status"] = "validated"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output.mkdir()
        with pytest.raises(FileExistsError, match="already exists"):
            import_pubmed(
                source,
                output,
                corpus="pubmed-test",
                source_version="2026 baseline",
                license_text="NLM terms",
            )


def test_pubmed_resume_rejects_changed_completed_shard() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "raw"
        output = root / "processed"
        _write_source(source, ["pubmed26n0001.xml.gz", "pubmed26n0002.xml.gz"])
        import_pubmed(
            source,
            output,
            corpus="pubmed-test",
            source_version="2026 baseline",
            license_text="NLM terms",
            max_files=1,
        )
        building = root / ".processed.pubmed-building"
        checkpoint = json.loads((building / "checkpoint.json").read_text(encoding="utf-8"))
        shard = building / checkpoint["parts"][0]["documents"]
        with shard.open("ab") as stream:
            stream.write(b"corruption")
        with pytest.raises(ValueError, match="size changed"):
            import_pubmed(
                source,
                output,
                corpus="pubmed-test",
                source_version="2026 baseline",
                license_text="NLM terms",
            )
