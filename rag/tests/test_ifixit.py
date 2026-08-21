from __future__ import annotations

import json
from pathlib import Path

import pytest

from offline_rag.bm25 import build_index, search
from offline_rag.ifixit import import_ifixit, parse_guide_html


GUIDE_HTML = """<!doctype html>
<html><head>
<meta name="title" content="Example Phone Battery Replacement - iFixit">
<meta name="description" content="Replace a worn battery safely.">
<link rel="canonical" href="https://www.ifixit.com/Guide/Example+Phone+Battery+Replacement/42">
</head><body>
<meta itemprop="datePublished" content="2025-01-02T03:04:05Z">
<meta itemprop="dateModified" content="2025-03-04T05:06:07Z">
<div class="react-component" data-name="FlagSectionComponent"
 data-props='{"difficultyName":"Moderate","timeRequired":"20 - 30 minutes"}'></div>
<div class="react-component" data-name="GuideTopComponent"
 data-props='{"productData":{"tools":[{"name":"Pentalobe P2 Screwdriver","quantity":1,"sku":"IF145-096"}],"parts":[{"name":"Example Phone Battery","quantity":1}]}}'></div>
<ol class="section-steps">
<li id="s100" class="step step-wrapper js-step" data-step-number="1">
 <div class="step" itemtype="http://schema.org/HowToStep">
  <span class="stepTitleTitle" itemprop="name">Power off the phone</span>
  <img data-biggest="https://example.test/step1.large" alt="Power button">
  <ul class="step-lines"><li class="level-0" itemtype="http://schema.org/HowToDirection">
   <div class="bullet bullet_red"></div><p itemprop="text">Warning: shut down the phone before opening it.</p>
  </li></ul>
 </div>
</li>
<li id="s101" class="step step-wrapper js-step" data-step-number="2">
 <div class="step" itemtype="http://schema.org/HowToStep">
  <span class="stepTitleTitle" itemprop="name">Disconnect the battery</span>
  <ul class="step-lines"><li class="level-1" itemtype="http://schema.org/HowToDirection">
   <div class="bullet bullet_black"></div><p itemprop="text">Lift the connector straight up with a spudger.</p>
  </li></ul>
 </div>
</li>
</ol>
</body></html>"""


def _write_zim(path: Path, *, guide_count: int = 1) -> None:
    libzim = pytest.importorskip("libzim.writer")

    class StringItem(libzim.Item):
        def __init__(self, title: str, article_path: str, content: str) -> None:
            super().__init__()
            self._title = title
            self._path = article_path
            self._content = content

        def get_path(self) -> str:
            return self._path

        def get_title(self) -> str:
            return self._title

        def get_mimetype(self) -> str:
            return "text/html"

        def get_contentprovider(self):
            return libzim.StringProvider(self._content)

        def get_hints(self):
            return {libzim.Hint.FRONT_ARTICLE: True}

    with libzim.Creator(path).config_indexing(True, "eng") as creator:
        creator.set_mainpath("Guide/Example+Phone+Battery+Replacement/42")
        for offset in range(guide_count):
            guide_id = 42 + offset
            title = "Example Phone Battery Replacement" if offset == 0 else f"Example Phone {offset + 1} Battery Replacement"
            article_path = f"Guide/{title.replace(' ', '+')}/{guide_id}"
            guide_html = GUIDE_HTML.replace("Example Phone Battery Replacement", title).replace("/42", f"/{guide_id}")
            creator.add_item(StringItem(title, article_path, guide_html))
        creator.add_item(StringItem("Navigation", "Other/Navigation", "<html><body>not a guide</body></html>"))
        for name, value in {
            "Creator": "offline-rag tests",
            "Description": "tiny synthetic iFixit fixture",
            "Name": "ifixit-test",
            "Publisher": "tests",
            "Title": "iFixit test",
            "Language": "eng",
            "Date": "2025-12-01",
        }.items():
            creator.add_metadata(name, value)


def test_parse_ifixit_guide_preserves_procedure_structure() -> None:
    guide = parse_guide_html("Guide/Example+Phone+Battery+Replacement/42", GUIDE_HTML)
    assert guide is not None
    assert guide.guide_id == "42"
    assert guide.title == "Example Phone Battery Replacement"
    assert guide.difficulty == "Moderate"
    assert guide.time_required == "20 - 30 minutes"
    assert guide.modified_at == "2025-03-04T05:06:07Z"
    assert [item["name"] for item in guide.tools] == ["Pentalobe P2 Screwdriver"]
    assert [item["name"] for item in guide.parts] == ["Example Phone Battery"]
    assert [(step.number, step.title) for step in guide.steps] == [
        (1, "Power off the phone"),
        (2, "Disconnect the battery"),
    ]
    assert guide.steps[0].lines[0].marker == "red"
    assert guide.steps[1].lines[0].level == 1
    assert guide.steps[0].images == ({"url": "https://example.test/step1.large", "alt": "Power button"},)


def test_parse_ifixit_rejects_non_guide_or_empty_procedure() -> None:
    assert parse_guide_html("Device/Example_Phone", GUIDE_HTML) is None
    assert parse_guide_html("Guide/Empty/99", "<html><head><title>Empty</title></head></html>") is None


def test_ifixit_import_and_bm25_citations(tmp_path: Path) -> None:
    source = tmp_path / "tiny.zim"
    output = tmp_path / "processed"
    database = tmp_path / "ifixit.sqlite3"
    _write_zim(source)

    result = import_ifixit(
        source,
        output,
        corpus="ifixit-test",
        source_version="2025-12-test",
        progress_interval=1,
    )
    assert result["documents"] == 1
    assert result["chunks"] == 3
    manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] is True
    assert manifest["counts"] == {"chunks": 3, "documents": 1}

    build_index(output, database)
    matches = search(database, "disconnect battery connector spudger", limit=3, mode="and")
    assert matches[0]["document_id"] == "ifixit-test:guide:42"
    assert matches[0]["source_url"] == "https://www.ifixit.com/Guide/Example+Phone+Battery+Replacement/42"
    assert "Step 2" in matches[0]["citation"]


def test_ifixit_output_protection_and_limit(tmp_path: Path) -> None:
    source = tmp_path / "tiny.zim"
    output = tmp_path / "processed"
    _write_zim(source, guide_count=2)
    import_ifixit(source, output, corpus="ifixit-test", source_version="test", max_guides=1)
    manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] is False
    assert manifest["stop_reason"] == "guide_limit"
    with pytest.raises(FileExistsError):
        import_ifixit(source, output, corpus="ifixit-test", source_version="test")


def test_ifixit_exact_limit_on_exhausted_source_is_complete(tmp_path: Path) -> None:
    source = tmp_path / "tiny.zim"
    output = tmp_path / "processed"
    _write_zim(source)
    import_ifixit(source, output, corpus="ifixit-test", source_version="test", max_guides=1)
    manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] is True
    assert manifest["stop_reason"] == "source_complete"
