from __future__ import annotations

import bz2
import re
from pathlib import Path


MEDIAWIKI_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page><title>Apollo Guidance Computer</title><ns>0</ns><id>100</id>
    <revision><id>200</id><timestamp>2026-08-01T00:00:00Z</timestamp>
      <text xml:space="preserve">The '''Apollo Guidance Computer''' was a digital computer. [[File:AGC.jpg|thumb|Computer photograph]]

== Software ==
Its software used rope memory and supported the Apollo missions.

=== Guidance programs ===
The guidance programs controlled navigation.</text>
    </revision>
  </page>
  <page><title>AGC</title><ns>0</ns><id>101</id><redirect title="Apollo Guidance Computer" />
    <revision><id>201</id><timestamp>2026-08-01T00:00:00Z</timestamp><text>#REDIRECT</text></revision>
  </page>
  <page><title>Talk:Apollo Guidance Computer</title><ns>1</ns><id>900</id>
    <revision><id>901</id><timestamp>2026-08-01T00:00:00Z</timestamp><text>Excluded talk page.</text></revision>
  </page>
  <page><title>Technical programming terms</title><ns>0</ns><id>102</id>
    <revision><id>202</id><timestamp>2026-08-01T00:00:00Z</timestamp>
      <text xml:space="preserve">The exact examples std::vector C++, C# .NET 8, and foo_bar appear here.

== Retrieval ==
Reciprocal rank fusion combines independently ranked result lists.</text>
    </revision>
  </page>
</mediawiki>"""


def write_archive(directory: Path, content: str = MEDIAWIKI_FIXTURE) -> Path:
    archive = directory / "fixture.xml.bz2"
    archive.write_bytes(bz2.compress(content.encode("utf-8")))
    return archive


def write_multistream_archive(directory: Path) -> tuple[Path, Path]:
    """Write a two-stream archive and its Wikimedia-style offset index."""

    pages = re.findall(r"<page>.*?</page>", MEDIAWIKI_FIXTURE, flags=re.DOTALL)
    groups = (pages[:2], pages[2:])
    header = MEDIAWIKI_FIXTURE[: MEDIAWIKI_FIXTURE.index("<page>")]
    footer = "\n</mediawiki>"
    archive_bytes = bytearray()
    index_lines: list[str] = []
    for group_index, group in enumerate(groups):
        offset = len(archive_bytes)
        fragment = (header if group_index == 0 else "") + "\n".join(group)
        if group_index == len(groups) - 1:
            fragment += footer
        archive_bytes.extend(bz2.compress(fragment.encode("utf-8")))
        for page in group:
            title = re.search(r"<title>(.*?)</title>", page, flags=re.DOTALL).group(1)
            page_id = re.search(r"<id>(\d+)</id>", page).group(1)
            index_lines.append(f"{offset}:{page_id}:{title}")
    archive = directory / "fixture-multistream.xml.bz2"
    index = directory / "fixture-multistream-index.txt.bz2"
    archive.write_bytes(bytes(archive_bytes))
    index.write_bytes(bz2.compress(("\n".join(index_lines) + "\n").encode("utf-8")))
    return archive, index
