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
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .records import CommonChunk, CommonDocument, make_content_id
from .rsync_acquisition import validate_snapshot


IANA_MANIFEST_SCHEMA_VERSION = 1
IANA_NAMESPACE = "http://www.iana.org/assignments"
RECOGNIZED_OUTPUT_FILES = frozenset(
    {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json", "extraction-stats.json"}
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if isinstance(child.tag, str) and _local(child.tag) == name]


def _first_text(element: ET.Element, name: str) -> str | None:
    children = _children(element, name)
    return _render(children[0]) if children else None


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _xref(element: ET.Element) -> str:
    kind = (element.get("type") or "reference").strip()
    data = (element.get("data") or _collapse("".join(element.itertext()))).strip()
    if kind.casefold() == "rfc" and data.casefold().startswith("rfc"):
        return f"RFC {data[3:]}"
    if kind.casefold() == "registry":
        return f"IANA registry {data}"
    return f"{kind}: {data}" if data else kind


def _render(element: ET.Element) -> str:
    parts: list[str] = [element.text or ""]
    for child in element:
        if not isinstance(child.tag, str):
            continue
        parts.append(_xref(child) if _local(child.tag) == "xref" else _render(child))
        parts.append(child.tail or "")
    return _collapse(" ".join(parts))


def _label(name: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").replace("-", " ")
    return " ".join(part.upper() if part.casefold() in {"id", "uri", "url", "rfc"} else part.capitalize() for part in value.split())


def _references(element: ET.Element) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        if isinstance(child.tag, str) and _local(child.tag) == "xref":
            value = _xref(child)
            if value and value not in values:
                values.append(value)
    return values


def _structured_fields(element: ET.Element) -> tuple[dict[str, Any], str]:
    fields: dict[str, list[str]] = {}
    rendered: list[str] = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        name = _local(child.tag)
        value = _xref(child) if name == "xref" else _render(child)
        if not value:
            continue
        key = "reference" if name == "xref" else name
        fields.setdefault(key, []).append(value)
        rendered.append(f"{_label(key)}: {value}")
    compact: dict[str, Any] = {
        name: values[0] if len(values) == 1 else values for name, values in fields.items()
    }
    return compact, "\n".join(rendered)


def _split_text(value: str, max_chars: int) -> Iterator[str]:
    remaining = value.strip()
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "), window.rfind(" "))
        if cut < max_chars // 2:
            cut = max_chars
        piece = remaining[:cut].strip()
        if piece:
            yield piece
        remaining = remaining[cut:].strip()
    if remaining:
        yield remaining


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(prefix: str, identity: Sequence[Any], length: int = 24) -> str:
    value = json.dumps(list(identity), ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:length]}"


def _chunk_id(document_id: str, source_version: str, ordinal: int, text: str) -> str:
    return _stable_id("", (document_id, source_version, ordinal, text), 32).removeprefix(":")


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
    actual = {path.name for path in output.iterdir()}
    if not {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json"}.issubset(actual) or not actual.issubset(
        RECOGNIZED_OUTPUT_FILES
    ):
        raise ValueError(f"Refusing to replace unrecognized or mixed output directory: {output}")
    backup = output.with_name(f".{output.name}.replaced-{uuid.uuid4().hex}")
    os.replace(output, backup)
    try:
        os.replace(temporary, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def _registry_elements(root: ET.Element) -> Iterator[tuple[ET.Element, tuple[str, ...], tuple[str, ...]]]:
    def walk(
        element: ET.Element,
        parent_ids: tuple[str, ...],
        parent_titles: tuple[str, ...],
    ) -> Iterator[tuple[ET.Element, tuple[str, ...], tuple[str, ...]]]:
        registry_id = (element.get("id") or "registry").strip()
        title = _first_text(element, "title") or registry_id
        identifiers = (*parent_ids, registry_id)
        titles = (*parent_titles, title)
        yield element, identifiers, titles
        for child in _children(element, "registry"):
            yield from walk(child, identifiers, titles)

    yield from walk(root, (), ())


def _metadata_chunks(element: ET.Element, heading: tuple[str, ...], max_chars: int) -> list[tuple[str, dict[str, Any]]]:
    lines: list[str] = []
    references: list[str] = []
    for name in ("description", "category", "created", "updated", "registration_rule", "expert", "range", "note", "footnote"):
        for child in _children(element, name):
            value = _render(child)
            if value:
                lines.append(f"{_label(name)}: {value}")
            for reference in _references(child):
                if reference not in references:
                    references.append(reference)
    direct_references = [_xref(child) for child in _children(element, "xref")]
    if direct_references:
        lines.append(f"References: {', '.join(dict.fromkeys(direct_references))}")
        for reference in direct_references:
            if reference not in references:
                references.append(reference)
    if not lines:
        return []
    value = f"Registry: {heading[-1]}\n" + "\n".join(lines)
    return [
        (piece, {"kind": "registry_metadata", "references": references, "part": part})
        for part, piece in enumerate(_split_text(value, max_chars))
    ]


def import_iana_registries(
    source_root: Path,
    output: Path,
    *,
    source_version: str,
    license_name: str,
    base_url: str = "https://www.iana.org/assignments/",
    max_chars: int = 3200,
    force: bool = False,
    require_snapshot_manifest: bool = True,
) -> dict[str, Any]:
    """Convert IANA registry XML tables into atomic common documents and chunks."""

    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if not source_version.strip() or not license_name.strip():
        raise ValueError("source_version and license_name must be nonempty")
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")
    source_manifest = validate_snapshot(source_root) if require_snapshot_manifest else None
    xml_files = sorted(source_root.rglob("*.xml"), key=lambda path: path.relative_to(source_root).as_posix())
    if not xml_files:
        raise ValueError(f"No XML files found under {source_root}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    documents_path = temporary / "documents.jsonl"
    chunks_path = temporary / "chunks.jsonl"
    started = datetime.now(timezone.utc)
    document_count = 0
    chunk_count = 0
    record_count = 0
    registry_file_count = 0
    skipped_non_registry = 0
    skipped_invalid_noncanonical = 0
    try:
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            for path in xml_files:
                relative = path.relative_to(source_root).as_posix()
                before = path.stat()
                try:
                    tree = ET.parse(path)
                except ET.ParseError:
                    if path.stem == path.parent.name:
                        raise
                    skipped_invalid_noncanonical += 1
                    continue
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"Source file changed during import: {path}")
                root = tree.getroot()
                if not isinstance(root.tag, str) or _local(root.tag) != "registry":
                    skipped_non_registry += 1
                    continue
                if root.tag.startswith("{") and root.tag.partition("}")[0].removeprefix("{") != IANA_NAMESPACE:
                    skipped_non_registry += 1
                    continue
                registry_file_count += 1
                source_sha256 = _sha256(path)
                root_updated = _first_text(root, "updated")
                page_relative = relative.removesuffix(".xml") + ".xhtml"
                xml_source_url = base_url.rstrip("/") + "/" + quote(relative, safe="/")
                for element, registry_ids, registry_titles in _registry_elements(root):
                    records = _children(element, "record")
                    heading = registry_titles
                    specifications: list[tuple[str, dict[str, Any]]] = _metadata_chunks(element, heading, max_chars)
                    for record_index, record in enumerate(records):
                        fields, rendered = _structured_fields(record)
                        if not rendered:
                            continue
                        text = f"Registry: {heading[-1]}\n{rendered}"
                        references = _references(record)
                        pieces = list(_split_text(text, max_chars))
                        for part, piece in enumerate(pieces):
                            specifications.append(
                                (
                                    piece,
                                    {
                                        "kind": "registry_record",
                                        "record_index": record_index,
                                        "record_part": part,
                                        "record_parts": len(pieces),
                                        "record_attributes": dict(record.attrib),
                                        "fields": fields,
                                        "references": references,
                                    },
                                )
                            )
                        record_count += 1
                    if not specifications:
                        continue
                    registry_id = registry_ids[-1]
                    document_id = _stable_id("iana", (relative, *registry_ids))
                    title = " — ".join(dict.fromkeys(registry_titles))
                    updated = _first_text(element, "updated") or root_updated
                    source_url = base_url.rstrip("/") + "/" + quote(page_relative, safe="/") + "#" + quote(registry_id)
                    document_text = "\n\n".join(value for value, _ in specifications)
                    document = CommonDocument(
                        document_id=document_id,
                        corpus="iana-protocol-registries",
                        title=title,
                        source_url=source_url,
                        source_version=source_version,
                        source_timestamp=updated,
                        license=license_name,
                        content_hash=make_content_id(document_text),
                        attributes={
                            "relative_path": relative,
                            "xml_source_url": xml_source_url,
                            "source_sha256": source_sha256,
                            "format": "iana-registry-xml",
                            "registry_id": registry_id,
                            "registry_path": list(registry_ids),
                            "registry_titles": list(registry_titles),
                            "parent_registry_id": registry_ids[-2] if len(registry_ids) > 1 else None,
                            "record_count": len(records),
                            "created": _first_text(element, "created"),
                            "updated": updated,
                            "category": _first_text(element, "category") or _first_text(root, "category"),
                        },
                    )
                    documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                    instance_ids = [
                        _chunk_id(document_id, source_version, ordinal, value)
                        for ordinal, (value, _) in enumerate(specifications)
                    ]
                    for ordinal, ((value, attributes), instance_id) in enumerate(
                        zip(specifications, instance_ids, strict=True)
                    ):
                        chunk_attributes = {
                            **attributes,
                            "relative_path": relative,
                            "registry_id": registry_id,
                            "section_index": ordinal,
                            "chunk_index": ordinal,
                        }
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
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())
        if document_count == 0 or chunk_count == 0 or record_count == 0:
            raise ValueError("IANA import produced no searchable registry records")
        files = {
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
        stats = {
            "schema_version": 1,
            "output_schema_version": 1,
            "completed": True,
            "stop_reason": "source_complete",
            "xml_files": len(xml_files),
            "registry_files": registry_file_count,
            "documents": document_count,
            "chunks": chunk_count,
            "records": record_count,
            "skipped_non_registry_xml": skipped_non_registry,
            "skipped_invalid_noncanonical_xml": skipped_invalid_noncanonical,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        manifest = {
            "schema_version": IANA_MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "corpus": "iana-protocol-registries",
            "source_version": source_version,
            "source_timestamp": source_manifest.get("acquired_at") if source_manifest else None,
            "license": license_name,
            "base_url": base_url,
            "completed": True,
            "stop_reason": "source_complete",
            "counts": {"documents": document_count, "chunks": chunk_count},
            "configuration": {
                "max_chars": max_chars,
                "root_element": f"{{{IANA_NAMESPACE}}}registry",
                "record_strategy": "one-record-per-chunk-with-oversize-splitting",
                "require_snapshot_manifest": require_snapshot_manifest,
            },
            "source_snapshot": source_manifest,
            "parts": [
                {
                    "part": 0,
                    "documents": documents_path.name,
                    "chunks": chunks_path.name,
                    "documents_sha256": files["documents"]["sha256"],
                    "chunks_sha256": files["chunks"]["sha256"],
                }
            ],
            "files": files,
        }
        _atomic_json(temporary / "extraction-stats.json", stats)
        _atomic_json(temporary / "corpus-manifest.json", manifest)
        _publish_directory(temporary, output, force)
        return {"output": str(output.resolve()), **stats}
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import verified IANA registry XML into common records.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--base-url", default="https://www.iana.org/assignments/")
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-unverified-source", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_iana_registries(
        args.source_root,
        args.output,
        source_version=args.source_version,
        license_name=args.license_name,
        base_url=args.base_url,
        max_chars=args.max_chars,
        force=args.force,
        require_snapshot_manifest=not args.allow_unverified_source,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
