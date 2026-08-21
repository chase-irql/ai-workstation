from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import unquote, urlparse

from .records import CommonChunk, CommonDocument, make_content_id, normalize_content


IFIXIT_MANIFEST_SCHEMA_VERSION = 1
IFIXIT_LICENSE = "CC-BY-NC-SA-3.0"
_GUIDE_PATH_RE = re.compile(r"(?:^|/)(Guide|Teardown)/(.+?)/(\d+)(?:$|[/?#])", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass(frozen=True)
class GuideLine:
    text: str
    level: int = 0
    marker: str | None = None


@dataclass(frozen=True)
class GuideStep:
    number: int
    title: str
    lines: tuple[GuideLine, ...]
    images: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class ParsedGuide:
    guide_id: str
    guide_type: str
    title: str
    source_url: str
    summary: str | None
    category: str | None
    difficulty: str | None
    time_required: str | None
    published_at: str | None
    modified_at: str | None
    tools: tuple[dict[str, Any], ...]
    parts: tuple[dict[str, Any], ...]
    steps: tuple[GuideStep, ...]


@dataclass
class _MutableStep:
    number: int
    title: str = ""
    lines: list[GuideLine] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", html.unescape(value)).strip()


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _clean(value)
    return cleaned or None


def _portable_product(item: object) -> dict[str, Any] | None:
    """Keep durable tool/part identity while discarding store-specific payload noise."""

    if not isinstance(item, dict):
        return None
    name = _string(item.get("name") or item.get("text") or item.get("title"))
    if not name:
        return None
    result: dict[str, Any] = {"name": name}
    for source, target in (
        ("quantity", "quantity"),
        ("notes", "notes"),
        ("type", "type"),
        ("wikiUrl", "wiki_url"),
        ("wiki_url", "wiki_url"),
        ("productUrl", "source_url"),
        ("url", "source_url"),
        ("sku", "sku"),
        ("isOptional", "optional"),
        ("isoptional", "optional"),
    ):
        value = item.get(source)
        if value not in (None, "", False):
            result[target] = value
    return result


class _GuideHTMLParser(HTMLParser):
    """Extract iFixit's visible HowTo microdata without indexing navigation or comments."""

    def __init__(self, article_path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.article_path = article_path
        self.depth = 0
        self.title: str | None = None
        self.summary: str | None = None
        self.canonical_url: str | None = None
        self.published_at: str | None = None
        self.modified_at: str | None = None
        self.category: str | None = None
        self.difficulty: str | None = None
        self.time_required: str | None = None
        self.tools: list[dict[str, Any]] = []
        self.parts: list[dict[str, Any]] = []
        self.steps: list[GuideStep] = []
        self._step: _MutableStep | None = None
        self._step_depth: int | None = None
        self._line_level = 0
        self._line_marker: str | None = None
        self._step_lines_depth: int | None = None
        self._product_section: str | None = None
        self._product_section_depth: int | None = None
        self._detail_field: str | None = None
        self._detail_depth: int | None = None
        self._capture: tuple[str, int, list[str]] | None = None

    @staticmethod
    def _attrs(values: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name.lower(): value or "" for name, value in values}

    def _capture_start(self, name: str) -> None:
        if self._capture is None:
            self._capture = (name, self.depth, [])

    def _react_data(self, attrs: dict[str, str]) -> None:
        name = attrs.get("data-name", "")
        payload = attrs.get("data-props")
        if not payload or name not in {"GuideTopComponent", "FlagSectionComponent"}:
            return
        try:
            value = json.loads(html.unescape(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if name == "GuideTopComponent":
            product = value.get("productData") if isinstance(value, dict) else None
            if isinstance(product, dict):
                self.tools = [result for item in product.get("tools", []) if (result := _portable_product(item))]
                self.parts = [result for item in product.get("parts", []) if (result := _portable_product(item))]
        elif isinstance(value, dict):
            self.difficulty = _string(value.get("difficultyName")) or self.difficulty
            self.time_required = _string(value.get("timeRequired")) or self.time_required

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID_TAGS:
            self.depth += 1
        attrs = self._attrs(attrs_list)
        classes = set(attrs.get("class", "").split())
        self._react_data(attrs)

        if tag == "div" and "item-list-tools" in classes:
            self._product_section, self._product_section_depth = "tool", self.depth
        elif tag == "div" and "item-list-parts" in classes:
            self._product_section, self._product_section_depth = "part", self.depth
        elif tag == "div" and "details-item" in classes:
            if "difficulty" in classes:
                self._detail_field, self._detail_depth = "difficulty", self.depth
            elif "time" in " ".join(classes).lower():
                self._detail_field, self._detail_depth = "time_required", self.depth

        if tag == "meta":
            name = attrs.get("name", "").lower()
            itemprop = attrs.get("itemprop", "").lower()
            content = _string(attrs.get("content"))
            if name == "description" and content:
                self.summary = content
            elif name == "title" and content and not self.title:
                self.title = re.sub(r"\s+-\s+iFixit$", "", content, flags=re.IGNORECASE)
            elif name == "keywords" and content:
                keywords = [_clean(part) for part in content.split(",") if _clean(part)]
                if len(keywords) > 1:
                    self.category = keywords[1]
            elif itemprop == "datepublished" and content:
                self.published_at = content
            elif itemprop == "datemodified" and content:
                self.modified_at = content
        if tag == "link" and "canonical" in attrs.get("rel", "").lower():
            candidate = _string(attrs.get("href"))
            if candidate and urlparse(candidate).netloc.endswith("ifixit.com"):
                self.canonical_url = candidate

        if tag == "li" and self._step is None and ({"step", "step-wrapper"} <= classes or "step-wrapper" in classes):
            raw_number = attrs.get("data-step-number", "")
            number = int(raw_number) if raw_number.isdigit() else len(self.steps) + 1
            self._step = _MutableStep(number=number)
            self._step_depth = self.depth
        elif self._step is None and tag == "div" and attrs.get("itemtype", "").endswith("/HowToStep"):
            self._step = _MutableStep(number=len(self.steps) + 1)
            self._step_depth = self.depth

        if self._step is not None:
            if tag == "span" and "stepTitleTitle" in classes:
                self._capture_start("step_title")
            elif tag == "strong" and "stepValue" in classes:
                self._capture_start("step_number")
            elif tag == "ul" and "step-lines" in classes:
                self._step_lines_depth = self.depth
            elif tag == "li" and (
                attrs.get("itemtype", "").endswith("/HowToDirection") or self._step_lines_depth is not None
            ):
                level_match = re.search(r"level-(\d+)", attrs.get("class", ""))
                self._line_level = int(level_match.group(1)) if level_match else 0
                icon_match = re.search(r"(?:bullet-line-icon|ico-step-icon)-([a-z]+)", attrs.get("class", ""), re.I)
                self._line_marker = icon_match.group(1).lower() if icon_match else None
            elif tag == "div":
                bullet = next((value[7:] for value in classes if value.startswith("bullet_") and value != "bullet_black"), None)
                if not bullet:
                    icon = next((value for value in classes if "step-icon-" in value), None)
                    bullet = icon.rsplit("-", 1)[-1] if icon else None
                if bullet:
                    self._line_marker = bullet
            elif tag == "p" and (attrs.get("itemprop", "").lower() == "text" or self._step_lines_depth is not None):
                self._capture_start("step_line")
            elif tag == "img":
                source = _string(attrs.get("data-biggest") or attrs.get("src"))
                if source:
                    source = re.sub(r"^\.\./\.\./images/(https?)/", r"\1://", source)
                    alternate = _string(attrs.get("alt"))
                    if not alternate and urlparse(source).netloc != "guide-images.cdn.ifixit.com":
                        return
                    image = {"url": source}
                    if alternate:
                        image["alt"] = alternate
                    if not any(existing["url"] == source for existing in self._step.images):
                        self._step.images.append(image)
        elif tag in {"h1", "title"} and not self.title:
            self._capture_start("title")

        if tag == "p" and attrs.get("itemprop", "").lower() == "name" and "title" in classes and self._product_section:
            self._capture_start(f"{self._product_section}_name")
        elif tag == "p" and "item-value" in classes and self._detail_field:
            self._capture_start(self._detail_field)

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture[2].append(data)

    def _finish_capture(self) -> None:
        if self._capture is None:
            return
        name, _, values = self._capture
        value = _clean(" ".join(values))
        if name == "title" and value:
            self.title = value
        elif name == "step_title" and value and self._step is not None:
            self._step.title = value
        elif name == "step_line" and value and self._step is not None:
            self._step.lines.append(GuideLine(value, self._line_level, self._line_marker))
        elif name == "step_number" and value and self._step is not None:
            match = re.search(r"\d+", value)
            if match:
                self._step.number = int(match.group())
        elif name == "tool_name" and value:
            self.tools.append({"name": value})
        elif name == "part_name" and value:
            self.parts.append({"name": value})
        elif name == "difficulty" and value:
            self.difficulty = value
        elif name == "time_required" and value:
            self.time_required = value
        self._capture = None

    def _finish_step(self) -> None:
        if self._step is None:
            return
        if self._step.lines:
            self.steps.append(
                GuideStep(
                    number=self._step.number,
                    title=self._step.title or f"Step {self._step.number}",
                    lines=tuple(self._step.lines),
                    images=tuple(self._step.images),
                )
            )
        self._step = None
        self._step_depth = None
        self._line_level = 0
        self._line_marker = None

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None and self._capture[1] == self.depth:
            self._finish_capture()
        if self._step_lines_depth == self.depth:
            self._step_lines_depth = None
        if self._product_section_depth == self.depth:
            self._product_section = None
            self._product_section_depth = None
        if self._detail_depth == self.depth:
            self._detail_field = None
            self._detail_depth = None
        if self._step is not None and self._step_depth == self.depth:
            self._finish_step()
        self.depth = max(0, self.depth - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        original_depth = self.depth
        self.handle_starttag(tag, attrs)
        self.depth = original_depth

    def close(self) -> None:
        super().close()
        self._finish_capture()
        self._finish_step()


def parse_guide_html(article_path: str, value: str) -> ParsedGuide | None:
    """Parse one iFixit Guide or Teardown page into ordered procedural fields."""

    match = _GUIDE_PATH_RE.search(unquote(article_path))
    if not match:
        return None
    parser = _GuideHTMLParser(article_path)
    parser.feed(value)
    parser.close()
    if not parser.title or not parser.steps:
        return None
    guide_type = match.group(1).lower()
    slug = _clean(match.group(2).replace("+", " ").replace("_", " "))
    category = parser.category
    if not category and parser.title:
        category = parser.title.removesuffix(" Replacement").removesuffix(" Teardown")
        if category == parser.title:
            category = slug or None
    source_url = parser.canonical_url or f"https://www.ifixit.com/{match.group(1)}/{match.group(2)}/{match.group(3)}"
    return ParsedGuide(
        guide_id=match.group(3),
        guide_type=guide_type,
        title=parser.title,
        source_url=source_url,
        summary=parser.summary,
        category=category,
        difficulty=parser.difficulty,
        time_required=parser.time_required,
        published_at=parser.published_at,
        modified_at=parser.modified_at,
        tools=tuple(parser.tools),
        parts=tuple(parser.parts),
        steps=tuple(parser.steps),
    )


def _split_text(text: str, max_chars: int) -> list[str]:
    normalized = normalize_content(text)
    if len(normalized) <= max_chars:
        return [normalized]
    lines = normalized.splitlines()
    pieces: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip() if current else line
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = line
        else:
            current = candidate
        while len(current) > max_chars:
            boundary = current.rfind(" ", 0, max_chars + 1)
            boundary = boundary if boundary >= max_chars // 2 else max_chars
            pieces.append(current[:boundary].strip())
            current = current[boundary:].strip()
    if current:
        pieces.append(current)
    return pieces


def _guide_chunks(guide: ParsedGuide, max_chars: int) -> list[tuple[list[str], str, dict[str, Any]]]:
    values: list[tuple[list[str], str, dict[str, Any]]] = []
    overview_lines = [guide.title]
    if guide.summary:
        overview_lines.append(guide.summary)
    for label, products in (("Tools", guide.tools), ("Parts", guide.parts)):
        if products:
            overview_lines.append(f"{label}: " + "; ".join(str(item["name"]) for item in products))
    details = [value for value in (guide.difficulty, guide.time_required) if value]
    if details:
        overview_lines.append("Difficulty and time: " + "; ".join(details))
    overview = normalize_content("\n".join(overview_lines))
    values.append(([guide.title, "Overview"], overview, {"kind": "overview", "section_index": 0, "chunk_index": 0}))
    for step_index, step in enumerate(guide.steps, start=1):
        fallback_title = f"Step {step.number}"
        lines = [fallback_title if step.title == fallback_title else f"{fallback_title}: {step.title}"]
        safety = False
        for line in step.lines:
            prefix = "  " * line.level + "- "
            if line.marker:
                prefix += f"[{line.marker.upper()}] "
            if line.marker in {"red", "yellow", "orange"} or re.search(r"\b(?:warning|caution|danger)\b", line.text, re.I):
                safety = True
            lines.append(prefix + line.text)
        for part, text in enumerate(_split_text("\n".join(lines), max_chars)):
            values.append(
                (
                    [guide.title, fallback_title] + ([] if step.title == fallback_title else [step.title]),
                    text,
                    {
                        "kind": "procedure_step",
                        "step_number": step.number,
                        "step_title": step.title,
                        "step_part": part,
                        "safety_sensitive": safety,
                        "images": list(step.images),
                        "section_index": step_index,
                        "chunk_index": len(values),
                    },
                )
            )
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


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


def _guide_entries(archive: Any) -> Iterator[Any]:
    for entry_id in range(int(archive.all_entry_count)):
        entry = archive._get_entry_by_id(entry_id)
        if entry.is_redirect:
            continue
        if _GUIDE_PATH_RE.search(unquote(entry.path)):
            yield entry


def import_ifixit(
    source: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    max_chars: int = 3200,
    max_guides: int | None = None,
    force: bool = False,
    progress_interval: int = 1000,
) -> dict[str, object]:
    """Convert an English iFixit Kiwix ZIM into atomic common-record JSONL files."""

    try:
        from libzim.reader import Archive
    except ImportError as error:  # pragma: no cover - exercised by deployment environments
        raise RuntimeError("iFixit ZIM ingestion requires the pinned 'libzim' package") from error
    if not source.is_file():
        raise FileNotFoundError(source)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", corpus):
        raise ValueError("corpus has invalid characters")
    if not source_version.strip() or max_chars < 256 or progress_interval < 1:
        raise ValueError("source version, max_chars >= 256, and a positive progress interval are required")
    if max_guides is not None and max_guides < 1:
        raise ValueError("max_guides must be positive when provided")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")

    archive = Archive(source)
    if archive.has_checksum and not archive.check():
        raise ValueError(f"ZIM internal checksum validation failed: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    documents_path = temporary / "documents.jsonl"
    chunks_path = temporary / "chunks.jsonl"
    started = datetime.now(timezone.utc)
    document_count = 0
    chunk_count = 0
    candidate_entries = 0
    skipped_invalid = 0
    guide_types: dict[str, int] = {}
    limited = False
    try:
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            for entry in _guide_entries(archive):
                if max_guides is not None and document_count >= max_guides:
                    limited = True
                    break
                candidate_entries += 1
                item = entry.get_item()
                if not item.mimetype.lower().startswith("text/html"):
                    skipped_invalid += 1
                    continue
                try:
                    raw = bytes(item.content)
                    value = raw.decode("utf-8", errors="strict")
                except (UnicodeDecodeError, RuntimeError):
                    skipped_invalid += 1
                    continue
                guide = parse_guide_html(entry.path, value)
                if guide is None:
                    skipped_invalid += 1
                    continue
                chunks = _guide_chunks(guide, max_chars)
                document_id = f"{corpus}:{guide.guide_type}:{guide.guide_id}"
                document_text = "\n\n".join(text for _, text, _ in chunks)
                document = CommonDocument(
                    document_id=document_id,
                    corpus=corpus,
                    title=guide.title,
                    source_url=guide.source_url,
                    source_version=source_version,
                    source_timestamp=guide.modified_at,
                    license=IFIXIT_LICENSE,
                    content_hash=make_content_id(document_text),
                    attributes={
                        "format": "ifixit-zim-html",
                        "guide_id": int(guide.guide_id),
                        "guide_type": guide.guide_type,
                        "category": guide.category,
                        "summary": guide.summary,
                        "difficulty": guide.difficulty,
                        "time_required": guide.time_required,
                        "published_at": guide.published_at,
                        "tools": list(guide.tools),
                        "parts": list(guide.parts),
                        "step_count": len(guide.steps),
                        "zim_path": entry.path,
                    },
                )
                documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                instance_ids = [
                    hashlib.sha256(
                        json.dumps([document_id, source_version, ordinal, heading, text], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()[:32]
                    for ordinal, (heading, text, _) in enumerate(chunks)
                ]
                for ordinal, ((heading, text, attributes), instance_id) in enumerate(zip(chunks, instance_ids, strict=True)):
                    chunk = CommonChunk(
                        chunk_instance_id=instance_id,
                        content_id=make_content_id(text),
                        document_id=document_id,
                        parent_chunk_id=None,
                        ordinal=ordinal,
                        heading_path=heading,
                        text=text,
                        character_count=len(text),
                        token_count=None,
                        previous_chunk_id=instance_ids[ordinal - 1] if ordinal else None,
                        next_chunk_id=instance_ids[ordinal + 1] if ordinal + 1 < len(instance_ids) else None,
                        attributes={**attributes, "guide_id": int(guide.guide_id), "guide_type": guide.guide_type},
                    )
                    chunks_stream.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                    chunk_count += 1
                document_count += 1
                guide_types[guide.guide_type] = guide_types.get(guide.guide_type, 0) + 1
                if document_count % progress_interval == 0:
                    print(f"iFixit import: {document_count:,} guides / {chunk_count:,} chunks", file=sys.stderr, flush=True)
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())
        if document_count == 0:
            raise ValueError("iFixit archive produced no valid guide documents")
        files = {
            "documents": {"path": "documents.jsonl", "bytes": documents_path.stat().st_size, "sha256": _sha256(documents_path)},
            "chunks": {"path": "chunks.jsonl", "bytes": chunks_path.stat().st_size, "sha256": _sha256(chunks_path)},
        }
        finished = datetime.now(timezone.utc)
        configuration = {"max_chars": max_chars, "max_guides": max_guides, "article_paths": ["Guide/", "Teardown/"]}
        manifest = {
            "schema_version": IFIXIT_MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "corpus": corpus,
            "source_version": source_version,
            "license": IFIXIT_LICENSE,
            "completed": not limited,
            "stop_reason": "guide_limit" if limited else "source_complete",
            "counts": {"documents": document_count, "chunks": chunk_count},
            "guide_types": guide_types,
            "configuration": configuration,
            "input": {
                "path": str(source.resolve()),
                "bytes": source.stat().st_size,
                "sha256": _sha256(source),
                "zim_uuid": str(archive.uuid),
                "zim_checksum": archive.checksum if archive.has_checksum else None,
                "all_entries": int(archive.all_entry_count),
            },
            "files": files,
            "parts": [{"part": 0, "documents": "documents.jsonl", "documents_sha256": files["documents"]["sha256"], "chunks": "chunks.jsonl", "chunks_sha256": files["chunks"]["sha256"]}],
        }
        stats = {
            "schema_version": 1,
            "completed": not limited,
            "stop_reason": "guide_limit" if limited else "source_complete",
            "documents": document_count,
            "chunks": chunk_count,
            "candidate_entries": candidate_entries,
            "skipped_invalid": skipped_invalid,
            "guide_types": guide_types,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        _atomic_json(temporary / "corpus-manifest.json", manifest)
        _atomic_json(temporary / "extraction-stats.json", stats)
        _publish_directory(temporary, output, force)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {"output": str(output.resolve()), "corpus": corpus, "documents": document_count, "chunks": chunk_count, "guide_types": guide_types}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an English iFixit Kiwix ZIM into common retrieval records.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--max-guides", type=int)
    parser.add_argument("--progress-interval", type=int, default=1000)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_ifixit(
        args.source,
        args.output,
        corpus=args.corpus,
        source_version=args.source_version,
        max_chars=args.max_chars,
        max_guides=args.max_guides,
        force=args.force,
        progress_interval=args.progress_interval,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
