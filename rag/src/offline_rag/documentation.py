from __future__ import annotations

import argparse
import copy
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
import xml.etree.ElementTree as ET
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
    {".html", ".htm", ".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".txt", ".man", ".roff", ".pod", ".xml"}
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
DOCBOOK_ENTITY_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_.:-]*);")
DOCBOOK_BUILTIN_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XI_INCLUDE = "{http://www.w3.org/2001/XInclude}include"


def _supported_source(path: Path) -> bool:
    return path.suffix.casefold() in SUPPORTED_SUFFIXES or path.name.casefold().endswith(".pod.in")


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
    if lines and lines[0].strip() == "---":
        closing = next((candidate for candidate in range(1, len(lines)) if lines[candidate].strip() == "---"), None)
        if closing is not None:
            for metadata_line in lines[1:closing]:
                key, separator, value = metadata_line.partition(":")
                if separator and key.strip().casefold() == "title":
                    title = value.strip().strip("'\"")
                    break
            index = closing + 1
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


MDOC_INLINE_MACROS = frozenset(
    {
        "Ad", "An", "Ap", "Ar", "At", "Bsx", "Bx", "Cd", "Cm", "Dv", "Dx", "Em", "Er", "Ev",
        "Fa", "Fd", "Fl", "Fn", "Ft", "Fx", "Ic", "Li", "Lk", "Ms", "Mt", "Nm", "No", "Ns",
        "Nx", "Ox", "Pa", "Pf", "Ql", "Sm", "St", "Sy", "Tn", "Ux", "Va", "Vt", "Xr",
    }
)


def _mdoc_text(value: str) -> str:
    """Remove common semantic mdoc markup while retaining its searchable terms."""

    cleaned = _roff_text(value)
    tokens = cleaned.split()
    output: list[str] = []
    for token in tokens:
        if token in MDOC_INLINE_MACROS or token in {"Xo", "Xc", "Oo", "Oc", "Do", "Dc", "Po", "Pc"}:
            continue
        output.append(token)
    return _clean_text(" ".join(output))


def parse_man(text: str, fallback_title: str) -> ParsedDocument:
    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    title = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        macro = MAN_MACRO_RE.match(line)
        if macro:
            name = macro.group(1).upper()
            value = _mdoc_text(macro.group(2))
            if name in {"TH", "DT"}:
                _flush_paragraph(blocks, headings, paragraph)
                title = value.split()[0] if value else title
            elif name == "SH":
                _flush_paragraph(blocks, headings, paragraph)
                headings = [value] if value else headings
            elif name == "SS":
                _flush_paragraph(blocks, headings, paragraph)
                headings = headings[:1] + ([value] if value else [])
            elif name in {"PP", "P", "LP", "TP", "IP", "HP", "RS", "RE", "BR", "IT"}:
                _flush_paragraph(blocks, headings, paragraph)
                if value:
                    paragraph.append(value)
            elif name in {
                "B", "I", "BI", "IB", "BR", "RB", "IR", "RI", "SM", "SB", "NM", "ND", "CM", "IC",
                "AR", "PA", "EV", "VA", "DV", "LI", "SY", "EM", "QL", "SQ", "DQ", "PQ", "XR", "SX",
                "FL", "NO", "PF", "OP", "LK", "MT", "ER", "FN", "FT", "FA",
            } and value:
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


def _pod_text(value: str) -> str:
    entities = {"lt": "<", "gt": ">", "sol": "/", "verbar": "|", "amp": "&", "quot": '"'}
    value = re.sub(r"E<([^<>]+)>", lambda match: entities.get(match.group(1), match.group(0)), value)
    # POD formatting codes can be nested. Repeating the innermost substitution
    # handles ordinary OpenSSL manual markup without pretending to implement a
    # complete Perl POD renderer.
    pattern = re.compile(r"([BICFSLXZ])<([^<>]*)>")
    while pattern.search(value):
        value = pattern.sub(
            lambda match: (
                match.group(2).split("|", 1)[0]
                if match.group(1) == "L" and "|" in match.group(2)
                else match.group(2)
            ),
            value,
        )
    return _clean_text(value)


def parse_pod(text: str, fallback_title: str) -> ParsedDocument:
    """Parse the structural subset of Perl POD used by OpenSSL manuals."""

    blocks: list[ContentBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []
    code: list[str] = []
    title = ""
    active = True

    def flush_code() -> None:
        nonlocal code
        value = _clean_text("\n".join(line[1:] if line.startswith((" ", "\t")) else line for line in code), preserve=True)
        if value:
            blocks.append(ContentBlock(tuple(headings), value, "code", {}))
        code = []

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = raw_line.strip()
        directive = re.match(r"^=(\w+)\s*(.*)$", stripped)
        if directive:
            flush_code()
            _flush_paragraph(blocks, headings, paragraph)
            name = directive.group(1).casefold()
            value = _pod_text(directive.group(2))
            if name == "cut":
                active = False
            elif name == "pod":
                active = True
            elif not active:
                continue
            elif name.startswith("head") and name[4:].isdigit():
                level = max(1, int(name[4:]))
                headings = headings[: level - 1]
                headings.append(value)
            elif name == "item" and value:
                paragraph.append(value)
            continue
        if not active:
            continue
        if raw_line.startswith((" ", "\t")) and stripped:
            _flush_paragraph(blocks, headings, paragraph)
            code.append(raw_line)
            continue
        flush_code()
        if not stripped:
            before = len(blocks)
            _flush_paragraph(blocks, headings, paragraph)
            if not title and headings and headings[-1].casefold() == "name" and len(blocks) > before:
                candidate = blocks[-1].text.split(" - ", 1)[0].strip()
                if candidate:
                    title = candidate
        else:
            paragraph.append(_pod_text(raw_line))
    flush_code()
    _flush_paragraph(blocks, headings, paragraph)
    if not title:
        name_block = next(
            (block for block in blocks if block.heading_path and block.heading_path[-1].casefold() == "name"),
            None,
        )
        if name_block is not None:
            candidate = name_block.text.split(" - ", 1)[0].strip()
            if candidate:
                title = candidate
    return ParsedDocument(title or fallback_title, tuple(blocks), "pod")


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _prepare_docbook_xml(text: str) -> str:
    """Make build-time DocBook entities deterministic without network DTD access."""

    return DOCBOOK_ENTITY_RE.sub(
        lambda match: match.group(0) if match.group(1) in DOCBOOK_BUILTIN_ENTITIES else match.group(1), text
    )


def _docbook_element_id(element: ET.Element) -> str | None:
    return element.get(XML_ID) or element.get("id")


def _load_docbook_fragment(path: Path, pointer: str) -> ET.Element | None:
    try:
        root = ET.fromstring(_prepare_docbook_xml(path.read_text(encoding="utf-8", errors="replace")))
    except (OSError, ET.ParseError):
        return None
    for element in root.iter():
        if _docbook_element_id(element) == pointer:
            return copy.deepcopy(element)
    return None


def _resolve_docbook_includes(root: ET.Element, source_path: Path | None) -> None:
    """Resolve systemd-style local XIncludes by ID, never external paths or URLs."""

    base = source_path.resolve().parent if source_path is not None else None
    for parent in list(root.iter()):
        for index, child in enumerate(list(parent)):
            if child.tag != XI_INCLUDE:
                continue
            href = child.get("href", "")
            pointer = child.get("xpointer", "")
            replacement: ET.Element | None = None
            if href == "version-info.xml" and re.fullmatch(r"v\d+", pointer):
                replacement = ET.Element("para")
                replacement.text = f"Added in systemd version {pointer[1:]}."
            elif base is not None and href and pointer and "://" not in href:
                candidate = (base / href).resolve()
                try:
                    candidate.relative_to(base)
                except ValueError:
                    candidate = Path()
                if candidate.is_file():
                    replacement = _load_docbook_fragment(candidate, pointer)
            if replacement is None:
                replacement = ET.Element("phrase")
            replacement.tail = child.tail
            parent.remove(child)
            parent.insert(index, replacement)


def _docbook_inline(element: ET.Element) -> str:
    name = _xml_local_name(element.tag)
    if name == "citerefentry":
        title = next(
            (_clean_text("".join(candidate.itertext())) for candidate in element if _xml_local_name(candidate.tag) == "refentrytitle"),
            "",
        )
        volume = next(
            (_clean_text("".join(candidate.itertext())) for candidate in element if _xml_local_name(candidate.tag) == "manvolnum"),
            "",
        )
        value = f"{title}({volume})" if title and volume else title or volume
    elif element.tag == XI_INCLUDE:
        pointer = element.get("xpointer", "")
        value = f"Added in systemd version {pointer[1:]}." if re.fullmatch(r"v\d+", pointer) else ""
    else:
        parts = [element.text or ""]
        for child in element:
            parts.append(_docbook_inline(child))
            parts.append(child.tail or "")
        value = "".join(parts)
    return value


def parse_docbook(text: str, fallback_title: str, source_path: Path | None = None) -> ParsedDocument:
    """Parse a DocBook reference into citation-friendly structured blocks."""

    try:
        root = ET.fromstring(_prepare_docbook_xml(text))
    except ET.ParseError as error:
        raise ValueError(f"invalid DocBook XML: {error}") from error
    _resolve_docbook_includes(root, source_path)

    def first_text(name: str) -> str:
        for element in root.iter():
            if _xml_local_name(element.tag) == name:
                value = _clean_text(_docbook_inline(element))
                if value:
                    return value
        return ""

    title = first_text("refentrytitle") or first_text("refname") or first_text("title") or fallback_title
    purpose = first_text("refpurpose")
    blocks: list[ContentBlock] = []
    if purpose:
        blocks.append(ContentBlock(("NAME",), f"{title} — {purpose}", "paragraph", {}))

    section_names = {"refsect1", "refsect2", "refsect3", "section", "chapter", "appendix"}
    code_names = {"programlisting", "screen", "literallayout", "synopsis", "cmdsynopsis", "funcsynopsis"}
    admonition_names = {"note", "warning", "tip", "important", "caution"}
    ignored_names = {"refentryinfo", "refmeta", "refnamediv", "title"}

    def attributes_for(element: ET.Element) -> dict[str, Any]:
        anchor = _docbook_element_id(element)
        return {"anchor": anchor} if anchor else {}

    def append_block(headings: tuple[str, ...], element: ET.Element, kind: str, *, preserve: bool = False) -> None:
        value = _clean_text(_docbook_inline(element), preserve=preserve)
        if value:
            blocks.append(ContentBlock(headings, value, kind, attributes_for(element)))

    def visit(element: ET.Element, headings: tuple[str, ...]) -> None:
        name = _xml_local_name(element.tag)
        if name in ignored_names:
            return
        if name in section_names or name in {"refsynopsisdiv", "refsection"}:
            section_title = next(
                (_clean_text(_docbook_inline(child)) for child in element if _xml_local_name(child.tag) == "title"),
                "Synopsis" if name == "refsynopsisdiv" else "",
            )
            nested = headings + ((section_title,) if section_title else ())
            for child in element:
                if _xml_local_name(child.tag) != "title":
                    visit(child, nested)
            return
        if name == "varlistentry":
            terms = [
                _clean_text(_docbook_inline(child)) for child in element if _xml_local_name(child.tag) == "term"
            ]
            term = ", ".join(item for item in terms if item)
            body = " ".join(
                _clean_text(_docbook_inline(child)) for child in element if _xml_local_name(child.tag) == "listitem"
            ).strip()
            value = f"{term}\n{body}".strip()
            if value:
                blocks.append(ContentBlock(headings + ((term,) if term else ()), value, "definition", attributes_for(element)))
            return
        if name in {"itemizedlist", "orderedlist", "simplelist"}:
            for child in element:
                if _xml_local_name(child.tag) in {"listitem", "member"}:
                    append_block(headings, child, "list_item")
            return
        if name in {"table", "informaltable"}:
            caption = next(
                (_clean_text(_docbook_inline(child)) for child in element if _xml_local_name(child.tag) == "title"), ""
            )
            table_headings = headings + ((caption,) if caption else ())
            for row in element.iter():
                if _xml_local_name(row.tag) == "row":
                    cells = [
                        _clean_text(_docbook_inline(cell))
                        for cell in row
                        if _xml_local_name(cell.tag) in {"entry", "td", "th"}
                    ]
                    value = " | ".join(cell for cell in cells if cell)
                    if value:
                        blocks.append(ContentBlock(table_headings, value, "table_row", attributes_for(row)))
            return
        if name in code_names:
            append_block(headings, element, "code", preserve=True)
            return
        if name in admonition_names or name == "example":
            label = next(
                (_clean_text(_docbook_inline(child)) for child in element if _xml_local_name(child.tag) == "title"),
                name.capitalize(),
            )
            nested = headings + (label,)
            for child in element:
                if _xml_local_name(child.tag) != "title":
                    visit(child, nested)
            return
        if name in {"para", "simpara", "formalpara", "blockquote", "bridgehead"}:
            append_block(headings, element, "paragraph")
            return
        for child in element:
            visit(child, headings)

    for child in root:
        visit(child, ())
    return ParsedDocument(title, tuple(blocks), "docbook")


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
    if suffix == ".pod" or path.name.casefold().endswith(".pod.in"):
        return parse_pod(text, fallback)
    if suffix == ".xml":
        return parse_docbook(text, fallback, path)
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
    decode_portable_names: bool = False,
) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        relative_name = relative.as_posix()
        if decode_portable_names:
            relative_name = "/".join(unquote(part) for part in relative_name.split("/"))
        if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if path.name.casefold() in IGNORED_FILE_NAMES or not _supported_source(path):
            continue
        if include_globs and not any(fnmatch.fnmatchcase(relative_name, pattern) for pattern in include_globs):
            continue
        if any(fnmatch.fnmatchcase(relative_name, pattern) for pattern in exclude_globs):
            continue
        files.append(path)
    def sort_name(item: Path) -> str:
        value = item.relative_to(root).as_posix()
        return "/".join(unquote(part) for part in value.split("/")) if decode_portable_names else value

    files.sort(key=lambda item: (sort_name(item).casefold(), sort_name(item)))
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
            and _supported_source(path)
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
    all_files = _source_files(
        content_root,
        None,
        include_globs,
        exclude_globs,
        decode_portable_names=portable_names_encoded,
    )
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
