from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin

from .records import CommonChunk, CommonDocument, make_content_id, normalize_content


DOCUMENTATION_MANIFEST_SCHEMA_VERSION = 1
PORTABLE_NAMES_MARKER = ".archive-name-encoding-v1.json"
SUPPORTED_SUFFIXES = frozenset(
    {".html", ".htm", ".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".txt", ".man", ".roff"}
    | {f".{number}" for number in range(1, 10)}
)
IGNORED_DIRECTORY_NAMES = frozenset({".git", ".hg", ".svn", "node_modules", "_static", "_sources"})
IGNORED_FILE_NAMES = frozenset({"search.html", "genindex.html", "py-modindex.html"})
CORPUS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
SETEXT_RE = re.compile(r"^\s*(=+|-+)\s*$")
RST_ADORNMENT_RE = re.compile(r"^\s*([=\-~^\"'`:+_*#<>])\1{2,}\s*$")
ASCIIDOC_HEADING_RE = re.compile(r"^(={1,6})\s+(.+?)\s*$")
ASCIIDOC_SETEXT_RE = re.compile(r"^\s*([=\-~^+])\1{2,}\s*$")
ASCIIDOC_DELIMITER_RE = re.compile(r"^(?:-{4,}|\.{4,})$")
MAN_MACRO_RE = re.compile(r"^\.([A-Za-z]{1,4})\s*(.*)$")
RFC_MARKER_RE = re.compile(r"(?im)^\s*(?:Request for Comments|RFC)\s*:\s*\d+")
RFC_HEADING_RE = re.compile(r"^\s{0,3}((?:[1-9]\d*)(?:\.\d+)*)\.\s{2,}(\S(?:.*\S)?)\s*$")
RFC_APPENDIX_HEADING_RE = re.compile(r"^\s{0,3}(Appendix\s+[A-Z](?:\.\d+)*)\.\s{2,}(\S(?:.*\S)?)\s*$", re.IGNORECASE)
RFC_TOC_ENTRY_RE = re.compile(r"\.{3,}\s+(?:\d+|[ivxlcdm]+)\s*$", re.IGNORECASE)
RFC_PAGE_DECORATION_RE = re.compile(
    r"^\s*(?:.*\[?Page\s+\d+\]?|RFC\s+\d+\s+.+|.+\s+\[[A-Z]+\s+\d{4}\])\s*$",
    re.IGNORECASE,
)
RFC_UNNUMBERED_HEADINGS = frozenset(
    {
        "abstract",
        "acknowledgements",
        "acknowledgments",
        "authors' addresses",
        "author's address",
        "copyright notice",
        "iana considerations",
        "introduction",
        "references",
        "security considerations",
        "status of this memo",
        "table of contents",
    }
)


@dataclass(frozen=True)
class ContentBlock:
    heading_path: tuple[str, ...]
    text: str
    kind: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    blocks: tuple[ContentBlock, ...]
    format: str


class _StructuredHTMLParser(HTMLParser):
    block_tags = {"p", "pre", "li", "dt", "dd", "blockquote", "figcaption", "td", "th"}
    ignored_tags = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}
    ignored_classes = {
        "related",
        "sphinxsidebar",
        "sphinxsidebarwrapper",
        "menu-wrapper",
        "toc",
        "toctree-wrapper",
        "contents",
        "breadcrumbs",
        "nosearch",
    }
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ContentBlock] = []
        self.title = ""
        self._headings: list[str] = []
        self._ignored_stack: list[str] = []
        self._capture_tag: str | None = None
        self._capture_depth = 0
        self._capture_parts: list[str] = []
        self._capture_attributes: dict[str, Any] = {}
        self._title_depth = 0
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self._ignored_stack:
            if tag not in self.void_tags:
                self._ignored_stack.append(tag)
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").casefold().split())
        role = (attributes.get("role") or "").casefold()
        if tag in self.ignored_tags or role in {"navigation", "search"} or classes.intersection(self.ignored_classes):
            if tag not in self.void_tags:
                self._ignored_stack = [tag]
            return
        if tag == "title":
            self._title_depth = 1
            return
        if self._title_depth:
            self._title_depth += 1
        if self._capture_tag is not None:
            if tag == "br":
                self._capture_parts.append("\n")
                return
            # Generated manuals commonly omit optional HTML end tags (for
            # example, ``<p>one<p>two`` or ``<p><dl>``). HTMLParser is a
            # tokenizer and does not apply the browser's implicit-closing
            # rules, so finish the current structural block before starting
            # another one. Inline markup remains part of the active block.
            if tag in self.block_tags or re.fullmatch(r"h[1-6]", tag):
                self._finish_capture()
            else:
                if tag not in self.void_tags:
                    self._capture_depth += 1
                return
        if tag in self.block_tags or re.fullmatch(r"h[1-6]", tag):
            self._capture_tag = tag
            self._capture_depth = 1
            self._capture_attributes = {
                key: value
                for key, value in {"id": attributes.get("id"), "class": attributes.get("class")}.items()
                if value
            }

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "br" and self._capture_tag is not None:
            self._capture_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._ignored_stack:
            for index in range(len(self._ignored_stack) - 1, -1, -1):
                if self._ignored_stack[index] == tag:
                    del self._ignored_stack[index:]
                    break
            return
        if self._title_depth:
            self._title_depth -= 1
            if self._title_depth == 0 and tag == "title":
                self.title = _collapse_whitespace("".join(self._title_parts))
            return
        if self._capture_tag is None:
            return
        self._capture_depth -= 1
        if self._capture_depth > 0:
            return
        self._finish_capture()

    def _finish_capture(self) -> None:
        if self._capture_tag is None:
            return
        captured_tag = self._capture_tag
        preserve = captured_tag == "pre"
        text = _clean_text("".join(self._capture_parts), preserve=preserve)
        if re.fullmatch(r"h[1-6]", captured_tag):
            text = text.removesuffix("¶").strip()
            if text:
                level = int(captured_tag[1])
                self._headings = self._headings[: level - 1]
                self._headings.append(text)
        elif text:
            self.blocks.append(
                ContentBlock(
                    tuple(self._headings),
                    text,
                    "code" if captured_tag == "pre" else captured_tag,
                    dict(self._capture_attributes),
                )
            )
        self._capture_tag = None
        self._capture_depth = 0
        self._capture_parts = []
        self._capture_attributes = {}

    def handle_data(self, data: str) -> None:
        if self._ignored_stack:
            return
        if self._title_depth:
            self._title_parts.append(data)
        if self._capture_tag is not None:
            self._capture_parts.append(data)


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _clean_text(value: str, *, preserve: bool = False) -> str:
    value = unicodedata.normalize("NFC", html.unescape(value)).replace("\r\n", "\n").replace("\r", "\n")
    if preserve:
        lines = [line.rstrip() for line in value.expandtabs(4).splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)
    return _collapse_whitespace(value)


def parse_html(text: str, fallback_title: str) -> ParsedDocument:
    parser = _StructuredHTMLParser()
    parser.feed(text)
    parser.close()
    title = parser.title or next((path[-1] for path in (block.heading_path for block in parser.blocks) if path), "")
    return ParsedDocument(title or fallback_title, tuple(parser.blocks), "html")


def _flush_paragraph(
    blocks: list[ContentBlock], headings: Sequence[str], lines: list[str], kind: str = "paragraph"
) -> None:
    if not lines:
        return
    text = _clean_text("\n".join(lines), preserve=kind == "code")
    if text:
        blocks.append(ContentBlock(tuple(headings), text, kind, {}))
    lines.clear()


def parse_markdown(text: str, fallback_title: str) -> ParsedDocument:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    code: list[str] = []
    fence: str | None = None
    fence_language: str | None = None
    title = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        fence_match = re.match(r"^\s*(```+|~~~+)\s*([^\s`]*)", line)
        if fence is not None:
            if stripped.startswith(fence[0] * len(fence)):
                attributes = {"language": fence_language} if fence_language else {}
                value = _clean_text("\n".join(code), preserve=True)
                if value:
                    blocks.append(ContentBlock(tuple(headings), value, "code", attributes))
                code = []
                fence = None
                fence_language = None
            else:
                code.append(line)
            index += 1
            continue
        if fence_match:
            _flush_paragraph(blocks, headings, paragraph)
            fence = fence_match.group(1)
            fence_language = fence_match.group(2) or None
            index += 1
            continue
        heading_match = ATX_HEADING_RE.match(line)
        if heading_match:
            _flush_paragraph(blocks, headings, paragraph)
            level = len(heading_match.group(1))
            heading = _clean_text(heading_match.group(2))
            headings = headings[: level - 1]
            headings.append(heading)
            title = title or heading
            index += 1
            continue
        if index + 1 < len(lines) and stripped and SETEXT_RE.match(lines[index + 1]):
            _flush_paragraph(blocks, headings, paragraph)
            level = 1 if lines[index + 1].lstrip().startswith("=") else 2
            heading = _clean_text(line)
            headings = headings[: level - 1]
            headings.append(heading)
            title = title or heading
            index += 2
            continue
        if not stripped:
            _flush_paragraph(blocks, headings, paragraph)
        elif line.startswith("    ") and not paragraph:
            indented: list[str] = []
            while index < len(lines) and (lines[index].startswith("    ") or not lines[index].strip()):
                indented.append(lines[index][4:] if lines[index].startswith("    ") else "")
                index += 1
            value = _clean_text("\n".join(indented), preserve=True)
            if value:
                blocks.append(ContentBlock(tuple(headings), value, "code", {}))
            continue
        else:
            paragraph.append(line)
        index += 1
    if fence is not None:
        value = _clean_text("\n".join(code), preserve=True)
        if value:
            blocks.append(ContentBlock(tuple(headings), value, "code", {"unterminated_fence": True}))
    _flush_paragraph(blocks, headings, paragraph)
    return ParsedDocument(title or fallback_title, tuple(blocks), "markdown")


def parse_rst(text: str, fallback_title: str) -> ParsedDocument:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    levels: dict[str, int] = {}
    paragraph: list[str] = []
    title = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if index + 1 < len(lines) and stripped:
            adornment = RST_ADORNMENT_RE.match(lines[index + 1])
            if adornment and len(lines[index + 1].strip()) >= len(stripped):
                _flush_paragraph(blocks, headings, paragraph)
                marker = adornment.group(1)
                level = levels.setdefault(marker, len(levels) + 1)
                headings = headings[: level - 1]
                headings.append(_clean_text(stripped))
                title = title or headings[-1]
                index += 2
                continue
        directive = re.match(r"^\s*\.\.\s+(code-block|sourcecode|code)::\s*(\S*)", line)
        if directive:
            _flush_paragraph(blocks, headings, paragraph)
            language = directive.group(2) or None
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            code: list[str] = []
            while index < len(lines) and (lines[index].startswith(("   ", "\t")) or not lines[index].strip()):
                code.append(lines[index][3:] if lines[index].startswith("   ") else lines[index].lstrip("\t"))
                index += 1
            value = _clean_text("\n".join(code), preserve=True)
            if value:
                blocks.append(
                    ContentBlock(tuple(headings), value, "code", {"language": language} if language else {})
                )
            continue
        if stripped.startswith(".. "):
            _flush_paragraph(blocks, headings, paragraph)
        elif not stripped:
            if paragraph and paragraph[-1].rstrip().endswith("::"):
                paragraph[-1] = paragraph[-1].rstrip()[:-1]
                _flush_paragraph(blocks, headings, paragraph)
                index += 1
                code = []
                while index < len(lines) and (lines[index].startswith(("   ", "\t")) or not lines[index].strip()):
                    code.append(lines[index][3:] if lines[index].startswith("   ") else lines[index].lstrip("\t"))
                    index += 1
                value = _clean_text("\n".join(code), preserve=True)
                if value:
                    blocks.append(ContentBlock(tuple(headings), value, "code", {}))
                continue
            _flush_paragraph(blocks, headings, paragraph)
        else:
            paragraph.append(line)
        index += 1
    _flush_paragraph(blocks, headings, paragraph)
    return ParsedDocument(title or fallback_title, tuple(blocks), "rst")


def parse_asciidoc(text: str, fallback_title: str) -> ParsedDocument:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    title = ""
    pending_language: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        heading = ASCIIDOC_HEADING_RE.match(line)
        if heading:
            _flush_paragraph(blocks, headings, paragraph)
            level = len(heading.group(1))
            value = _clean_text(heading.group(2))
            if level == 1 and not title:
                title = value
                headings = []
            else:
                effective = max(1, level - 1)
                headings = headings[: effective - 1]
                headings.append(value)
            index += 1
            continue
        if index + 1 < len(lines) and stripped and not stripped.startswith("["):
            underline = ASCIIDOC_SETEXT_RE.match(lines[index + 1])
            if underline and len(lines[index + 1].strip()) >= min(3, len(stripped)):
                _flush_paragraph(blocks, headings, paragraph)
                level = {"=": 1, "-": 2, "~": 3, "^": 4, "+": 5}[underline.group(1)]
                value = _clean_text(stripped)
                if level == 1 and not title:
                    title = value
                    headings = []
                else:
                    effective = max(1, level - 1)
                    headings = headings[: effective - 1]
                    headings.append(value)
                index += 2
                continue
        source = re.match(r"^\[source(?:,([^\]]+))?\]\s*$", stripped, flags=re.IGNORECASE)
        if source:
            _flush_paragraph(blocks, headings, paragraph)
            pending_language = source.group(1)
            index += 1
            continue
        if ASCIIDOC_DELIMITER_RE.fullmatch(stripped):
            _flush_paragraph(blocks, headings, paragraph)
            delimiter = stripped
            index += 1
            code: list[str] = []
            while index < len(lines) and lines[index].strip() != delimiter:
                code.append(lines[index])
                index += 1
            value = _clean_text("\n".join(code), preserve=True)
            if value:
                attributes = {"language": pending_language} if pending_language else {}
                blocks.append(ContentBlock(tuple(headings), value, "code", attributes))
            pending_language = None
            index += 1 if index < len(lines) else 0
            continue
        if stripped.startswith((":", "//")):
            _flush_paragraph(blocks, headings, paragraph)
        elif not stripped:
            _flush_paragraph(blocks, headings, paragraph)
        else:
            paragraph.append(line)
        index += 1
    _flush_paragraph(blocks, headings, paragraph)
    return ParsedDocument(title or fallback_title, tuple(blocks), "asciidoc")


def _roff_text(value: str) -> str:
    value = re.sub(r"\\f[BRIP]", "", value)
    value = value.replace(r"\-", "-").replace(r"\&", "").replace(r"\e", "\\")
    value = re.sub(r"\\\([a-zA-Z0-9]{2}", "", value)
    value = value.replace('"', "")
    return _clean_text(value)


def parse_man(text: str, fallback_title: str) -> ParsedDocument:
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    title = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        macro = MAN_MACRO_RE.match(line)
        if macro:
            name = macro.group(1).upper()
            value = _roff_text(macro.group(2))
            if name == "TH":
                _flush_paragraph(blocks, headings, paragraph)
                title = value.split()[0] if value else title
            elif name == "SH":
                _flush_paragraph(blocks, headings, paragraph)
                headings = [value] if value else headings
            elif name == "SS":
                _flush_paragraph(blocks, headings, paragraph)
                headings = headings[:1] + ([value] if value else [])
            elif name in {"PP", "P", "LP", "TP", "IP", "HP", "RS", "RE", "BR"}:
                _flush_paragraph(blocks, headings, paragraph)
                if value:
                    paragraph.append(value)
            elif name in {"B", "I", "BI", "IB", "BR", "RB", "IR", "RI", "SM", "SB"} and value:
                paragraph.append(value)
            continue
        if line.startswith(".\\\"") or line.startswith(".\""):
            continue
        value = _roff_text(line)
        if value:
            paragraph.append(value)
        else:
            _flush_paragraph(blocks, headings, paragraph)
    _flush_paragraph(blocks, headings, paragraph)
    return ParsedDocument(title or fallback_title, tuple(blocks), "man")


def parse_text(text: str, fallback_title: str) -> ParsedDocument:
    blocks: list[ContentBlock] = []
    paragraph: list[str] = []
    page = 1
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if "\f" in line:
            _flush_paragraph(blocks, (), paragraph)
            page += line.count("\f")
            line = line.replace("\f", "")
        if line.strip():
            paragraph.append(line)
        else:
            before = len(blocks)
            _flush_paragraph(blocks, (), paragraph)
            if len(blocks) > before:
                block = blocks[-1]
                blocks[-1] = ContentBlock(block.heading_path, block.text, block.kind, {"page": page})
    _flush_paragraph(blocks, (), paragraph)
    return ParsedDocument(fallback_title, tuple(blocks), "text")


def _rfc_title(lines: Sequence[str], fallback_title: str) -> str:
    """Extract an RFC title from either early field-style or modern front matter."""

    first_page = list(lines[:180])
    for line in first_page:
        match = re.match(r"^\s*Title\s*:\s*(\S.*)$", line, re.IGNORECASE)
        if match:
            return _clean_text(match.group(1))

    marker_index = next((index for index, line in enumerate(first_page) if RFC_MARKER_RE.search(line)), None)
    if marker_index is None:
        return fallback_title
    start = marker_index + 1
    while start < len(first_page) and first_page[start].strip():
        start += 1
    while start < len(first_page) and not first_page[start].strip():
        start += 1

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in first_page[start:]:
        if "\f" in line:
            break
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)

    rejected = RFC_UNNUMBERED_HEADINGS | {"network working group", "internet engineering task force"}
    for paragraph in paragraphs:
        value = _clean_text(" ".join(paragraph))
        folded = value.casefold()
        if not (3 <= len(value) <= 240) or folded in rejected:
            continue
        if RFC_PAGE_DECORATION_RE.match(value) or RFC_MARKER_RE.search(value):
            continue
        if any(re.match(r"^(?:Author|Category|ISSN|Obsoletes|Updates|Stream|Intended Status)\s*:", part, re.IGNORECASE) for part in paragraph):
            continue
        return value
    return fallback_title


def _rfc_metadata(text: str) -> dict[str, Any]:
    """Read stable publication metadata from the RFC's first-page header."""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()[:120]

    def field(name: str) -> str | None:
        pattern = re.compile(rf"^\s*{re.escape(name)}\s*:\s*(.+?)\s*$", re.IGNORECASE)
        for line in lines:
            match = pattern.match(line)
            if match:
                # RFC headers use a wide gap before the author/date column.
                return re.split(r"\s{2,}", match.group(1).strip(), maxsplit=1)[0]
        return None

    attributes: dict[str, Any] = {}
    rfc_number = field("Request for Comments") or field("Request for Comment")
    if rfc_number and (match := re.match(r"\d+", rfc_number)):
        attributes["rfc_number"] = int(match.group())
    for name in ("obsoletes", "updates"):
        value = field(name)
        if value:
            attributes[name] = [int(number) for number in re.findall(r"\d+", value)]
    category = field("Category")
    if category:
        attributes["publication_status"] = category
    issn = field("ISSN")
    if issn:
        attributes["issn"] = issn
    header = "\n".join(lines[:30])
    dates = re.findall(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        header,
        re.IGNORECASE,
    )
    if dates:
        attributes["publication_date"] = dates[-1]
    return attributes


def parse_rfc(text: str, fallback_title: str) -> ParsedDocument:
    """Parse canonical RFC text while retaining its numbered section hierarchy.

    RFC text is deliberately not reflowed beyond paragraph whitespace cleanup. Page
    furniture is removed only when it matches conservative header/footer patterns.
    """

    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    title = _rfc_title(lines, fallback_title)
    for index, raw_line in enumerate(lines):
        line = raw_line.replace("\f", "")
        stripped = line.strip()
        if not stripped:
            _flush_paragraph(blocks, headings, paragraph)
            continue
        if RFC_PAGE_DECORATION_RE.match(stripped):
            _flush_paragraph(blocks, headings, paragraph)
            continue
        if RFC_TOC_ENTRY_RE.search(stripped):
            _flush_paragraph(blocks, headings, paragraph)
            continue
        heading_match = RFC_HEADING_RE.match(line)
        if heading_match and len(heading_match.group(2)) <= 160:
            _flush_paragraph(blocks, headings, paragraph)
            number = heading_match.group(1)
            value = _clean_text(heading_match.group(2))
            level = number.count(".") + 1
            headings = headings[: level - 1]
            headings.append(f"{number}. {value}")
            continue
        appendix_match = RFC_APPENDIX_HEADING_RE.match(line)
        if appendix_match and len(appendix_match.group(2)) <= 160:
            _flush_paragraph(blocks, headings, paragraph)
            heading = f"{appendix_match.group(1)}. {_clean_text(appendix_match.group(2))}"
            headings = [heading]
            continue
        previous_blank = index == 0 or not lines[index - 1].strip()
        next_blank = index + 1 == len(lines) or not lines[index + 1].strip()
        if previous_blank and next_blank and stripped.casefold() in RFC_UNNUMBERED_HEADINGS:
            _flush_paragraph(blocks, headings, paragraph)
            headings = [_clean_text(stripped)]
            continue
        paragraph.append(line)
    _flush_paragraph(blocks, headings, paragraph)
    return ParsedDocument(title, tuple(blocks), "rfc-text")


def parse_document(path: Path, text: str) -> ParsedDocument:
    fallback = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return parse_html(text, fallback)
    if suffix in {".md", ".markdown"}:
        return parse_markdown(text, fallback)
    if suffix == ".rst":
        return parse_rst(text, fallback)
    if suffix in {".adoc", ".asciidoc"}:
        return parse_asciidoc(text, fallback)
    if suffix in {".man", ".roff"} or suffix in {f".{number}" for number in range(1, 10)}:
        return parse_man(text, fallback)
    if MAN_MACRO_RE.match(text.lstrip().splitlines()[0] if text.strip() else ""):
        return parse_man(text, fallback)
    if suffix == ".txt" and RFC_MARKER_RE.search(text[:12000]):
        return parse_rfc(text, fallback)
    return parse_text(text, fallback)


def _split_oversized(value: str, max_chars: int) -> Iterator[str]:
    remaining = value.strip()
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        candidates = [window.rfind(separator) for separator in ("\n\n", "\n", ". ", "; ", ", ", " ")]
        cut = max((candidate for candidate in candidates if candidate >= max_chars // 2), default=max_chars)
        if cut < 1:
            cut = max_chars
        piece = remaining[:cut].strip()
        if piece:
            yield piece
        remaining = remaining[cut:].strip()
    if remaining:
        yield remaining


def chunk_blocks(blocks: Sequence[ContentBlock], max_chars: int, min_chars: int) -> list[tuple[tuple[str, ...], str, dict[str, Any]]]:
    chunks: list[tuple[tuple[str, ...], str, dict[str, Any]]] = []
    current_heading: tuple[str, ...] = ()
    current_parts: list[str] = []
    current_kinds: list[str] = []
    current_attributes: dict[str, Any] = {}

    def flush() -> None:
        nonlocal current_parts, current_kinds, current_attributes
        text = "\n\n".join(part for part in current_parts if part).strip()
        if text:
            attributes = dict(current_attributes)
            attributes["block_kinds"] = sorted(set(current_kinds))
            chunks.append((current_heading, text, attributes))
        current_parts = []
        current_kinds = []
        current_attributes = {}

    for block in blocks:
        parts = list(_split_oversized(block.text, max_chars))
        for part in parts:
            addition = len(part) + (2 if current_parts else 0)
            if current_parts and (block.heading_path != current_heading or sum(map(len, current_parts)) + addition > max_chars):
                flush()
            if not current_parts:
                current_heading = block.heading_path
            current_parts.append(part)
            current_kinds.append(block.kind)
            current_attributes.update(block.attributes)
            if len(part) >= max_chars:
                flush()
    flush()
    if len(chunks) >= 2 and len(chunks[-1][1]) < min_chars and chunks[-2][0] == chunks[-1][0]:
        combined = f"{chunks[-2][1]}\n\n{chunks[-1][1]}"
        if len(combined) <= max_chars:
            attributes = dict(chunks[-2][2])
            attributes["block_kinds"] = sorted(
                set(attributes.get("block_kinds", [])) | set(chunks[-1][2].get("block_kinds", []))
            )
            chunks[-2:] = [(chunks[-1][0], combined, attributes)]
    return chunks


def _source_files(
    root: Path,
    max_files: int | None,
    include_globs: Sequence[str] = (),
    exclude_globs: Sequence[str] = (),
) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        relative_name = relative.as_posix()
        if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if path.name.casefold() in IGNORED_FILE_NAMES or path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            continue
        if include_globs and not any(fnmatch.fnmatchcase(relative_name, pattern) for pattern in include_globs):
            continue
        if any(fnmatch.fnmatchcase(relative_name, pattern) for pattern in exclude_globs):
            continue
        files.append(path)
    files.sort(key=lambda item: (item.relative_to(root).as_posix().casefold(), item.relative_to(root).as_posix()))
    return files[:max_files] if max_files is not None else files


def _content_root(root: Path) -> Path:
    """Discard archive wrapper directories without making them part of stable IDs."""

    current = root
    while True:
        direct_sources = [
            path
            for path in current.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and path.name.casefold() not in IGNORED_FILE_NAMES
            and path.suffix.casefold() in SUPPORTED_SUFFIXES
        ]
        child_directories = [
            path
            for path in current.iterdir()
            if path.is_dir() and not path.is_symlink() and path.name not in IGNORED_DIRECTORY_NAMES
        ]
        if direct_sources or len(child_directories) != 1:
            return current
        current = child_directories[0]


def _read_source(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), digest
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Unable to decode documentation source: {path}")


def _stable_id(corpus: str, relative: str) -> str:
    digest = hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:24]
    return f"{corpus}:{digest}"


def _case_collision_id(corpus: str, relative: str) -> str:
    """Disambiguate rare case-distinct upstream paths without changing ordinary stable IDs."""

    identity = f"case-sensitive-path\0{relative}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{corpus}:{digest}"


def _instance_id(document_id: str, version: str, ordinal: int, heading: Sequence[str], text: str) -> str:
    identity = json.dumps([document_id, version, ordinal, list(heading), text], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _publish_directory(temporary: Path, output: Path, force: bool) -> None:
    if not output.exists():
        os.replace(temporary, output)
        return
    if not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")
    if not output.is_dir():
        raise ValueError(f"Refusing to replace non-directory output: {output}")
    recognized = {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json", "extraction-stats.json"}
    actual = {path.name for path in output.iterdir()}
    if not {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json"}.issubset(actual) or not actual.issubset(recognized):
        raise ValueError(f"Refusing to replace unrecognized or mixed output directory: {output}")
    backup = output.with_name(f".{output.name}.replaced-{uuid.uuid4().hex}")
    os.replace(output, backup)
    try:
        os.replace(temporary, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def import_documentation(
    source_root: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    license_name: str,
    base_url: str | None = None,
    source_url_template: str | None = None,
    source_timestamp: str | None = None,
    include_globs: Sequence[str] = (),
    exclude_globs: Sequence[str] = (),
    max_chars: int = 3200,
    min_chars: int = 300,
    max_files: int | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Convert a documentation tree into validated common records atomically."""

    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if not CORPUS_RE.fullmatch(corpus):
        raise ValueError("corpus must use lowercase letters, numbers, dots, underscores, or hyphens")
    if not source_version.strip() or not license_name.strip():
        raise ValueError("source_version and license_name must be nonempty")
    if source_url_template is not None and "{relative_path}" not in source_url_template:
        raise ValueError("source_url_template must contain {relative_path}")
    if max_chars < 128:
        raise ValueError("max_chars must be at least 128")
    if min_chars < 0 or min_chars > max_chars:
        raise ValueError("min_chars must be between zero and max_chars")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files must be positive")
    if any(not pattern.strip() for pattern in (*include_globs, *exclude_globs)):
        raise ValueError("include and exclude glob patterns must be nonempty")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")
    portable_names_encoded = (source_root / PORTABLE_NAMES_MARKER).is_file()
    content_root = _content_root(source_root)
    all_files = _source_files(content_root, None, include_globs, exclude_globs)
    files = all_files[:max_files] if max_files is not None else all_files
    if not files:
        raise ValueError(f"No supported documentation files found under {source_root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    documents_path = temporary / "documents.jsonl"
    chunks_path = temporary / "chunks.jsonl"
    document_count = 0
    chunk_count = 0
    skipped_empty = 0
    source_bytes = 0
    formats: dict[str, int] = {}
    document_paths_by_id: dict[str, str] = {}
    started = datetime.now(timezone.utc)
    try:
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            for path in files:
                before = path.stat()
                text, source_sha256 = _read_source(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"Source file changed during import: {path}")
                relative = path.relative_to(content_root).as_posix()
                if portable_names_encoded:
                    relative = "/".join(unquote(part) for part in relative.split("/"))
                parsed = parse_document(path, text)
                chunk_values = chunk_blocks(parsed.blocks, max_chars, min_chars)
                if not chunk_values:
                    skipped_empty += 1
                    continue
                document_id = _stable_id(corpus, relative)
                prior_relative = document_paths_by_id.get(document_id)
                case_collision = prior_relative is not None and prior_relative != relative
                if case_collision:
                    document_id = _case_collision_id(corpus, relative)
                    conflicting_relative = document_paths_by_id.get(document_id)
                    if conflicting_relative is not None and conflicting_relative != relative:
                        raise ValueError(
                            "Stable document ID collision between "
                            f"{conflicting_relative!r} and {relative!r}"
                        )
                document_paths_by_id[document_id] = relative
                document_text = "\n\n".join(value for _, value, _ in chunk_values)
                encoded_relative = quote(relative, safe="/")
                if source_url_template:
                    source_url = source_url_template.format(relative_path=encoded_relative)
                else:
                    source_url = urljoin(base_url.rstrip("/") + "/", encoded_relative) if base_url else None
                document = CommonDocument(
                    document_id=document_id,
                    corpus=corpus,
                    title=parsed.title,
                    source_url=source_url,
                    source_version=source_version,
                    source_timestamp=source_timestamp,
                    license=license_name,
                    content_hash=make_content_id(document_text),
                    attributes={
                        "relative_path": relative,
                        "source_sha256": source_sha256,
                        "format": parsed.format,
                        **({"case_distinct_path_collision": True} if case_collision else {}),
                        **(_rfc_metadata(text) if parsed.format == "rfc-text" else {}),
                    },
                )
                documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                instance_ids = [
                    _instance_id(document_id, source_version, ordinal, heading, value)
                    for ordinal, (heading, value, _) in enumerate(chunk_values)
                ]
                for ordinal, ((heading, value, attributes), instance_id) in enumerate(zip(chunk_values, instance_ids, strict=True)):
                    chunk_attributes = dict(attributes)
                    chunk_attributes.update(
                        {"relative_path": relative, "section_index": ordinal, "chunk_index": ordinal}
                    )
                    chunk = CommonChunk(
                        chunk_instance_id=instance_id,
                        content_id=make_content_id(value),
                        document_id=document_id,
                        parent_chunk_id=None,
                        ordinal=ordinal,
                        heading_path=list(heading),
                        text=value,
                        character_count=len(value),
                        token_count=None,
                        previous_chunk_id=instance_ids[ordinal - 1] if ordinal else None,
                        next_chunk_id=instance_ids[ordinal + 1] if ordinal + 1 < len(instance_ids) else None,
                        attributes=chunk_attributes,
                    )
                    chunks_stream.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                    chunk_count += 1
                document_count += 1
                source_bytes += before.st_size
                formats[parsed.format] = formats.get(parsed.format, 0) + 1
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())
        if document_count == 0 or chunk_count == 0:
            raise ValueError("Documentation import produced no searchable records")
        files_manifest = {
            "documents": {
                "path": documents_path.name,
                "bytes": documents_path.stat().st_size,
                "sha256": _sha256(documents_path),
            },
            "chunks": {
                "path": chunks_path.name,
                "bytes": chunks_path.stat().st_size,
                "sha256": _sha256(chunks_path),
            },
        }
        finished = datetime.now(timezone.utc)
        complete_source = max_files is None or max_files >= len(all_files)
        stats = {
            "schema_version": 1,
            "output_schema_version": 1,
            "completed": complete_source,
            "stop_reason": "source_complete" if complete_source else "file_limit",
            "source_files": len(files),
            "available_source_files": len(all_files),
            "documents": document_count,
            "chunks": chunk_count,
            "skipped_empty": skipped_empty,
            "source_bytes": source_bytes,
            "formats": formats,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        manifest = {
            "schema_version": DOCUMENTATION_MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "corpus": corpus,
            "source_version": source_version,
            "source_timestamp": source_timestamp,
            "license": license_name,
            "base_url": base_url,
            "source_url_template": source_url_template,
            "completed": complete_source,
            "stop_reason": stats["stop_reason"],
            "counts": {"documents": document_count, "chunks": chunk_count},
            "configuration": {
                "max_chars": max_chars,
                "min_chars": min_chars,
                "max_files": max_files,
                "include_globs": list(include_globs),
                "exclude_globs": list(exclude_globs),
            },
            "parts": [
                {
                    "part": 0,
                    "documents": documents_path.name,
                    "chunks": chunks_path.name,
                    "documents_sha256": files_manifest["documents"]["sha256"],
                    "chunks_sha256": files_manifest["chunks"]["sha256"],
                }
            ],
            "files": files_manifest,
        }
        _atomic_json(temporary / "extraction-stats.json", stats)
        _atomic_json(temporary / "corpus-manifest.json", manifest)
        _publish_directory(temporary, output, force)
        return {
            "output": str(output.resolve()),
            "corpus": corpus,
            "source_version": source_version,
            "documents": document_count,
            "chunks": chunk_count,
            "source_files": len(files),
            "skipped_empty": skipped_empty,
        }
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import structured software and system documentation.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--source-url-template")
    parser.add_argument("--source-timestamp")
    parser.add_argument("--include-glob", action="append", default=[])
    parser.add_argument("--exclude-glob", action="append", default=[])
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_documentation(
        args.source_root,
        args.output,
        corpus=args.corpus,
        source_version=args.source_version,
        license_name=args.license_name,
        base_url=args.base_url,
        source_url_template=args.source_url_template,
        source_timestamp=args.source_timestamp,
        include_globs=args.include_glob,
        exclude_globs=args.exclude_glob,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        max_files=args.max_files,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
