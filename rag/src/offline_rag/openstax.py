from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from .documentation import ContentBlock, _clean_text, chunk_blocks, prepare_xml_entities
from .records import CommonChunk, CommonDocument, make_content_id


OPENSTAX_MANIFEST_SCHEMA_VERSION = 1
COLLECTION_NS = "http://cnx.rice.edu/collxml"
METADATA_NS = "http://cnx.rice.edu/mdml"
CNXML_NS = "http://cnx.rice.edu/cnxml"


@dataclass(frozen=True)
class ModuleOccurrence:
    book_slug: str
    book_title: str
    book_ordinal: int
    hierarchy: tuple[str, ...]
    module_id: str
    module_ordinal: int
    license_name: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _first_child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            value = _clean_text("".join(child.itertext()))
            if value:
                return value
    return ""


def parse_collection(path: Path, book_ordinal: int) -> list[ModuleOccurrence]:
    """Return modules in deterministic book/chapter order from one CollXML file."""

    root = ET.fromstring(path.read_text(encoding="utf-8"))
    if _local_name(root.tag) != "collection":
        raise ValueError(f"OpenStax collection has unexpected root: {path}")
    metadata = next((child for child in root if _local_name(child.tag) == "metadata"), None)
    if metadata is None:
        raise ValueError(f"OpenStax collection has no metadata: {path}")
    book_title = next(
        (_clean_text(element.text or "") for element in metadata if _local_name(element.tag) == "title"), ""
    )
    book_slug = next(
        (_clean_text(element.text or "") for element in metadata if _local_name(element.tag) == "slug"), ""
    )
    license_element = next((element for element in metadata if _local_name(element.tag) == "license"), None)
    license_name = _clean_text("".join(license_element.itertext())) if license_element is not None else ""
    if not book_title or not book_slug or not license_name:
        raise ValueError(f"OpenStax collection metadata is incomplete: {path}")
    content = next((child for child in root if _local_name(child.tag) == "content"), None)
    if content is None:
        raise ValueError(f"OpenStax collection has no content: {path}")
    occurrences: list[ModuleOccurrence] = []

    def visit(container: ET.Element, hierarchy: tuple[str, ...]) -> None:
        for child in container:
            name = _local_name(child.tag)
            if name == "module":
                module_id = (child.get("document") or "").strip()
                if not re.fullmatch(r"[A-Za-z0-9._-]+", module_id):
                    raise ValueError(f"Invalid OpenStax module ID {module_id!r} in {path}")
                occurrences.append(
                    ModuleOccurrence(
                        book_slug=book_slug,
                        book_title=book_title,
                        book_ordinal=book_ordinal,
                        hierarchy=hierarchy,
                        module_id=module_id,
                        module_ordinal=len(occurrences),
                        license_name=license_name,
                    )
                )
            elif name == "subcollection":
                title = _first_child_text(child, "title")
                nested_content = next((item for item in child if _local_name(item.tag) == "content"), None)
                if nested_content is None:
                    raise ValueError(f"OpenStax subcollection has no content in {path}")
                visit(nested_content, hierarchy + ((title,) if title else ()))

    visit(content, ())
    if not occurrences:
        raise ValueError(f"OpenStax collection references no modules: {path}")
    return occurrences


def _math_text(element: ET.Element) -> str:
    name = _local_name(element.tag)
    children = list(element)
    own = _clean_text(element.text or "")
    values = [_math_text(child) for child in children]
    if name == "mfrac" and len(values) >= 2:
        return f"({values[0]})/({values[1]})"
    if name == "msup" and len(values) >= 2:
        return f"{values[0]}^({values[1]})"
    if name == "msub" and len(values) >= 2:
        return f"{values[0]}_({values[1]})"
    if name == "msubsup" and len(values) >= 3:
        return f"{values[0]}_({values[1]})^({values[2]})"
    if name == "msqrt":
        return f"sqrt({' '.join(value for value in values if value) or own})"
    if name == "mroot" and len(values) >= 2:
        return f"root[{values[1]}]({values[0]})"
    if name == "mfenced":
        return f"({', '.join(value for value in values if value)})"
    combined = " ".join(value for value in (own, *values) if value)
    return _clean_text(combined)


def _inline(element: ET.Element, anchors: dict[str, str] | None = None) -> str:
    name = _local_name(element.tag)
    if name == "math":
        return _math_text(element)
    if name in {"image", "media"}:
        return _clean_text(element.get("alt", "") or element.get("src", ""))
    if name in {"newline", "br"}:
        return "\n"
    parts = [element.text or ""]
    for child in element:
        rendered = _inline(child, anchors)
        if not rendered and _local_name(child.tag) == "link":
            target = child.get("target-id", "")
            rendered = (anchors or {}).get(target) or child.get("document") or child.get("url", "")
        parts.extend((rendered, child.tail or ""))
    return "".join(parts)


def parse_cnxml(text: str, fallback_title: str) -> tuple[str, tuple[ContentBlock, ...], dict[str, str]]:
    """Parse one OpenStax CNXML module without resolving external media."""

    try:
        root = ET.fromstring(prepare_xml_entities(text))
    except ET.ParseError as error:
        raise ValueError(f"invalid OpenStax CNXML: {error}") from error
    if _local_name(root.tag) != "document":
        raise ValueError(f"unsupported OpenStax CNXML root: {_local_name(root.tag)}")
    metadata = next((child for child in root if _local_name(child.tag) == "metadata"), None)
    module_metadata: dict[str, str] = {}
    if metadata is not None:
        for element in metadata:
            name = _local_name(element.tag)
            if name in {"content-id", "uuid", "title"}:
                value = _clean_text("".join(element.itertext()))
                if value:
                    module_metadata[name.replace("-", "_")] = value
    title = _first_child_text(root, "title") or module_metadata.get("title") or fallback_title
    content = next((child for child in root if _local_name(child.tag) == "content"), None)
    if content is None:
        return title, (), module_metadata
    blocks: list[ContentBlock] = []
    anchors = {
        identifier: label
        for element in root.iter()
        if (identifier := element.get("id"))
        if (label := _first_child_text(element, "title"))
    }

    def attributes(element: ET.Element) -> dict[str, Any]:
        return {key: value for key, value in element.attrib.items() if key in {"id", "class", "type"} and value}

    def append(element: ET.Element, headings: tuple[str, ...], kind: str, *, preserve: bool = False) -> None:
        value = _clean_text(_inline(element, anchors), preserve=preserve)
        if value:
            blocks.append(ContentBlock(headings, value, kind, attributes(element)))

    def visit(element: ET.Element, headings: tuple[str, ...]) -> None:
        name = _local_name(element.tag)
        if name == "title":
            return
        if name == "section":
            section_title = _first_child_text(element, "title")
            nested = headings + ((section_title,) if section_title else ())
            for child in element:
                visit(child, nested)
            return
        if name in {"example", "exercise", "problem", "solution", "definition", "rule"}:
            explicit = _first_child_text(element, "title")
            label = explicit or name.replace("_", " ").title()
            nested = headings + (label,)
            for child in element:
                visit(child, nested)
            return
        if name in {"para", "statement", "meaning", "commentary"}:
            append(element, headings, "paragraph")
            return
        if name in {"code", "preformat"}:
            append(element, headings, "code", preserve=True)
            return
        if name in {"note", "warning", "tip"}:
            label = _first_child_text(element, "title") or (element.get("class") or name).replace("-", " ").title()
            nested = headings + (label,)
            append(element, nested, "admonition")
            return
        if name == "list":
            for child in element:
                visit(child, headings)
            return
        if name in {"item", "listitem"}:
            append(element, headings, "list_item")
            return
        if name == "figure":
            caption = next((child for child in element if _local_name(child.tag) == "caption"), None)
            media = next((child for child in element if _local_name(child.tag) == "media"), None)
            parts = []
            if media is not None:
                parts.append(_clean_text(_inline(media, anchors)))
            if caption is not None:
                parts.append(_clean_text(_inline(caption, anchors)))
            value = " — ".join(part for part in parts if part)
            if value:
                blocks.append(ContentBlock(headings, value, "figure_caption", attributes(element)))
            return
        if name in {"media", "image"}:
            append(element, headings, "figure_alt")
            return
        if name == "table":
            for row in element.iter():
                if _local_name(row.tag) not in {"row", "tr"}:
                    continue
                cells = [
                    _clean_text(_inline(cell, anchors))
                    for cell in row
                    if _local_name(cell.tag) in {"entry", "td", "th"}
                ]
                value = " | ".join(cell for cell in cells if cell)
                if value:
                    blocks.append(ContentBlock(headings, value, "table_row", attributes(row)))
            return
        if name in {"equation", "math"}:
            append(element, headings, "equation")
            return
        for child in element:
            visit(child, headings)

    for child in content:
        visit(child, ())
    return title, tuple(blocks), module_metadata


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


def import_openstax(
    source_root: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    source_url_template: str,
    max_chars: int = 3200,
    min_chars: int = 300,
    force: bool = False,
) -> dict[str, object]:
    """Convert OpenStax CollXML/CNXML into atomic common-record files."""

    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", corpus):
        raise ValueError("corpus has invalid characters")
    if not source_version.strip() or "{relative_path}" not in source_url_template:
        raise ValueError("source version and URL template are required")
    if max_chars < 128 or min_chars < 0 or min_chars > max_chars:
        raise ValueError("invalid chunk size configuration")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")
    collection_paths = sorted((source_root / "collections").glob("*.collection.xml"), key=lambda path: path.name)
    if not collection_paths:
        raise ValueError("No OpenStax collection manifests found")
    occurrences = [item for ordinal, path in enumerate(collection_paths) for item in parse_collection(path, ordinal)]
    identities = [(item.book_slug, item.module_id) for item in occurrences]
    if len(identities) != len(set(identities)):
        raise ValueError("OpenStax collection repeats a module within one book")
    occurrences_by_module: dict[str, list[ModuleOccurrence]] = {}
    for occurrence in occurrences:
        occurrences_by_module.setdefault(occurrence.module_id, []).append(occurrence)
    canonical_occurrences = [values[0] for values in occurrences_by_module.values()]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    documents_path = temporary / "documents.jsonl"
    chunks_path = temporary / "chunks.jsonl"
    started = datetime.now(timezone.utc)
    document_count = 0
    chunk_count = 0
    source_bytes = 0
    try:
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            for occurrence in canonical_occurrences:
                relative = f"modules/{occurrence.module_id}/index.cnxml"
                path = source_root / "modules" / occurrence.module_id / "index.cnxml"
                if not path.is_file() or path.is_symlink():
                    raise FileNotFoundError(f"Referenced OpenStax module is unavailable: {relative}")
                before = path.stat()
                data = path.read_bytes()
                text = data.decode("utf-8-sig")
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"OpenStax source changed during import: {path}")
                title, blocks, metadata = parse_cnxml(text, occurrence.module_id)
                prefixed = tuple(
                    ContentBlock((occurrence.book_title, *occurrence.hierarchy, *block.heading_path), block.text, block.kind, block.attributes)
                    for block in blocks
                )
                chunk_values = chunk_blocks(prefixed, max_chars, min_chars)
                if not chunk_values:
                    raise ValueError(f"OpenStax module produced no searchable content: {relative}")
                document_id = f"{corpus}:{occurrence.module_id}"
                document_text = "\n\n".join(value for _, value, _ in chunk_values)
                source_url = source_url_template.format(relative_path=quote(relative, safe="/"))
                document = CommonDocument(
                    document_id=document_id,
                    corpus=corpus,
                    title=title,
                    source_url=source_url,
                    source_version=source_version,
                    license=occurrence.license_name,
                    content_hash=make_content_id(document_text),
                    attributes={
                        "format": "cnxml",
                        "book_slug": occurrence.book_slug,
                        "book_title": occurrence.book_title,
                        "book_ordinal": occurrence.book_ordinal,
                        "chapter_path": list(occurrence.hierarchy),
                        "module_id": occurrence.module_id,
                        "module_ordinal": occurrence.module_ordinal,
                        "book_occurrences": [
                            {
                                "book_slug": item.book_slug,
                                "book_title": item.book_title,
                                "book_ordinal": item.book_ordinal,
                                "chapter_path": list(item.hierarchy),
                                "module_ordinal": item.module_ordinal,
                            }
                            for item in occurrences_by_module[occurrence.module_id]
                        ],
                        "module_uuid": metadata.get("uuid"),
                        "relative_path": relative,
                        "source_sha256": hashlib.sha256(data).hexdigest(),
                    },
                )
                documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                instance_ids = [
                    hashlib.sha256(
                        json.dumps(
                            [document_id, source_version, ordinal, list(heading), value],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()[:32]
                    for ordinal, (heading, value, _) in enumerate(chunk_values)
                ]
                for ordinal, ((heading, value, attributes), instance_id) in enumerate(
                    zip(chunk_values, instance_ids, strict=True)
                ):
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
                        attributes={
                            **attributes,
                            "book_slug": occurrence.book_slug,
                            "book_ordinal": occurrence.book_ordinal,
                            "chapter_path": list(occurrence.hierarchy),
                            "module_id": occurrence.module_id,
                            "module_ordinal": occurrence.module_ordinal,
                            "section_index": ordinal,
                            "chunk_index": ordinal,
                        },
                    )
                    chunks_stream.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                    chunk_count += 1
                document_count += 1
                source_bytes += len(data)
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())
        files = {
            "documents": {"path": "documents.jsonl", "bytes": documents_path.stat().st_size, "sha256": _sha256(documents_path)},
            "chunks": {"path": "chunks.jsonl", "bytes": chunks_path.stat().st_size, "sha256": _sha256(chunks_path)},
        }
        finished = datetime.now(timezone.utc)
        counts_by_book: dict[str, int] = {}
        for occurrence in occurrences:
            counts_by_book[occurrence.book_slug] = counts_by_book.get(occurrence.book_slug, 0) + 1
        configuration = {"max_chars": max_chars, "min_chars": min_chars, "collection_files": [path.name for path in collection_paths]}
        manifest = {
            "schema_version": OPENSTAX_MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "corpus": corpus,
            "source_version": source_version,
            "license": "per-book CollXML metadata",
            "completed": True,
            "stop_reason": "source_complete",
            "counts": {"documents": document_count, "chunks": chunk_count},
            "books": counts_by_book,
            "module_occurrences": len(occurrences),
            "configuration": configuration,
            "files": files,
            "parts": [{"part": 0, "documents": "documents.jsonl", "documents_sha256": files["documents"]["sha256"], "chunks": "chunks.jsonl", "chunks_sha256": files["chunks"]["sha256"]}],
        }
        stats = {
            "schema_version": 1,
            "output_schema_version": 1,
            "completed": True,
            "stop_reason": "source_complete",
            "books": len(collection_paths),
            "documents": document_count,
            "chunks": chunk_count,
            "module_occurrences": len(occurrences),
            "source_files": document_count + len(collection_paths),
            "source_bytes": source_bytes + sum(path.stat().st_size for path in collection_paths),
            "modules_by_book": counts_by_book,
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
    return {"output": str(output.resolve()), "corpus": corpus, "books": len(collection_paths), "documents": document_count, "chunks": chunk_count}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import OpenStax CollXML/CNXML into common retrieval records.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--source-url-template", required=True)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = import_openstax(
        args.source_root,
        args.output,
        corpus=args.corpus,
        source_version=args.source_version,
        source_url_template=args.source_url_template,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
