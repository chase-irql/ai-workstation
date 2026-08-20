from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import Destination

from .documentation import ContentBlock, chunk_blocks
from .records import CommonChunk, CommonDocument, make_content_id, normalize_content


PDF_MANUAL_MANIFEST_SCHEMA_VERSION = 1
CORPUS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ROMAN_PAGE_LABEL_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(corpus: str, relative: str) -> str:
    digest = hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:24]
    return f"{corpus}:{digest}"


def _case_collision_id(corpus: str, relative: str) -> str:
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
    required = {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json"}
    if not required.issubset(actual) or not actual.issubset(recognized):
        raise ValueError(f"Refusing to replace unrecognized or mixed output directory: {output}")
    backup = output.with_name(f".{output.name}.replaced-{uuid.uuid4().hex}")
    os.replace(output, backup)
    try:
        os.replace(temporary, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def _pdf_files(source: Path) -> tuple[Path, list[Path]]:
    if source.is_file():
        if source.suffix.casefold() != ".pdf":
            raise ValueError(f"PDF source file must use the .pdf extension: {source}")
        return source.parent, [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = [path for path in source.rglob("*.pdf") if path.is_file() and not path.is_symlink()]
    files.sort(key=lambda path: (path.relative_to(source).as_posix().casefold(), path.relative_to(source).as_posix()))
    if not files:
        raise ValueError(f"No PDF files found under {source}")
    return source, files


def _metadata_text(metadata: Any, key: str) -> str | None:
    if not metadata:
        return None
    value = metadata.get(key)
    if value is None:
        return None
    normalized = normalize_content(str(value))
    return normalized or None


def _walk_outline(reader: PdfReader, items: Iterable[Any], parents: tuple[str, ...] = ()) -> Iterator[tuple[int, tuple[str, ...]]]:
    """Yield page-numbered outline paths while tolerating malformed bookmarks."""

    last_title: str | None = None
    for item in items:
        if isinstance(item, list):
            yield from _walk_outline(reader, item, parents + ((last_title,) if last_title else ()))
            continue
        title = normalize_content(str(getattr(item, "title", "")))
        last_title = title or None
        if not isinstance(item, Destination) or not title:
            continue
        try:
            page_number = reader.get_destination_page_number(item)
        except (KeyError, TypeError, ValueError):
            continue
        if page_number is not None and page_number >= 0:
            yield page_number, parents + (title,)


def _outline_paths(reader: PdfReader, page_count: int) -> list[tuple[str, ...]]:
    starts: dict[int, tuple[str, ...]] = {}
    try:
        for page_number, path in _walk_outline(reader, reader.outline):
            if page_number < page_count:
                starts[page_number] = path
    except (AttributeError, PdfReadError, RecursionError, TypeError, ValueError):
        return [()] * page_count
    current: tuple[str, ...] = ()
    result: list[tuple[str, ...]] = []
    for page_number in range(page_count):
        current = starts.get(page_number, current)
        result.append(current)
    return result


def _extract_page_text(page: Any) -> str:
    try:
        # Layout mode otherwise drops rotated table labels and diagram text.
        # Including them may slightly degrade spacing on those pages, but losing
        # searchable error labels and callouts is worse for technical manuals.
        value = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False) or ""
    except (TypeError, ValueError, KeyError):
        value = page.extract_text() or ""
    return normalize_content(value)


def _page_has_images(page: Any) -> bool:
    try:
        return len(page.images) > 0
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _source_url(
    relative: str,
    *,
    base_url: str | None,
    source_url_template: str | None,
) -> str | None:
    encoded = quote(relative, safe="/")
    if source_url_template:
        return source_url_template.format(relative_path=encoded)
    return urljoin(base_url.rstrip("/") + "/", encoded) if base_url else None


def import_pdf_manuals(
    source: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    license_name: str,
    base_url: str | None = None,
    source_url_template: str | None = None,
    source_timestamp: str | None = None,
    max_chars: int = 3200,
    min_chars: int = 300,
    min_searchable_ratio: float = 0.5,
    max_files: int | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Convert text-layer PDFs into page-aware common records atomically.

    This importer deliberately does not perform OCR. A PDF with too many
    image-only pages fails before publication, making the missing OCR step
    visible rather than publishing a deceptively incomplete corpus.
    """

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
    if not 0.0 <= min_searchable_ratio <= 1.0:
        raise ValueError("min_searchable_ratio must be between zero and one")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files must be positive")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")

    source_root, all_files = _pdf_files(source)
    files = all_files[:max_files] if max_files is not None else all_files
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    documents_path = temporary / "documents.jsonl"
    chunks_path = temporary / "chunks.jsonl"
    started = datetime.now(timezone.utc)
    document_paths_by_id: dict[str, str] = {}
    totals = {
        "documents": 0,
        "chunks": 0,
        "pages": 0,
        "text_pages": 0,
        "image_only_pages": 0,
        "blank_pages": 0,
        "source_bytes": 0,
    }
    try:
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            for path in files:
                before = path.stat()
                source_sha256 = _sha256(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"Source file changed during import: {path}")
                relative = path.relative_to(source_root).as_posix()
                try:
                    reader = PdfReader(path, strict=False)
                except (PdfReadError, OSError, ValueError) as error:
                    raise ValueError(f"Unable to read PDF {relative}: {error}") from error
                if reader.is_encrypted:
                    try:
                        decrypted = reader.decrypt("")
                    except (NotImplementedError, PdfReadError, ValueError) as error:
                        raise ValueError(f"Encrypted PDF requires a password and cannot be imported: {relative}") from error
                    if not decrypted:
                        raise ValueError(f"Encrypted PDF requires a password and cannot be imported: {relative}")
                page_count = len(reader.pages)
                if page_count < 1:
                    raise ValueError(f"PDF contains no pages: {relative}")
                try:
                    labels = list(reader.page_labels)
                except (AttributeError, KeyError, TypeError, ValueError):
                    labels = [str(index + 1) for index in range(page_count)]
                if len(labels) != page_count:
                    labels = [str(index + 1) for index in range(page_count)]
                outline_paths = _outline_paths(reader, page_count)
                page_values: list[tuple[int, str, tuple[str, ...], str, list[tuple[tuple[str, ...], str, dict[str, Any]]]]] = []
                text_pages = image_only_pages = blank_pages = 0
                for page_index, page in enumerate(reader.pages):
                    text = _extract_page_text(page)
                    label = normalize_content(str(labels[page_index])) or str(page_index + 1)
                    page_heading = outline_paths[page_index] + (f"Page {label}",)
                    if text:
                        text_pages += 1
                        page_attributes: dict[str, Any] = {
                            "page_number": page_index + 1,
                            "page_label": label,
                        }
                        if ROMAN_PAGE_LABEL_RE.fullmatch(label):
                            page_attributes["front_matter"] = True
                        blocks = (ContentBlock(page_heading, text, "pdf-page", page_attributes),)
                        chunks = chunk_blocks(blocks, max_chars=max_chars, min_chars=min_chars)
                    else:
                        chunks = []
                        if _page_has_images(page):
                            image_only_pages += 1
                        else:
                            blank_pages += 1
                    page_values.append((page_index + 1, label, page_heading, text, chunks))
                relevant_pages = text_pages + image_only_pages
                searchable_ratio = text_pages / relevant_pages if relevant_pages else 0.0
                if text_pages == 0:
                    raise ValueError(f"PDF has no searchable text and requires OCR: {relative}")
                if relevant_pages and searchable_ratio < min_searchable_ratio:
                    raise ValueError(
                        f"PDF searchable-page ratio {searchable_ratio:.3f} is below {min_searchable_ratio:.3f}; OCR required: {relative}"
                    )

                metadata = reader.metadata
                title = _metadata_text(metadata, "/Title") or path.stem.replace("_", " ").replace("-", " ").strip()
                document_id = _stable_id(corpus, relative)
                prior_relative = document_paths_by_id.get(document_id)
                case_collision = prior_relative is not None and prior_relative != relative
                if case_collision:
                    document_id = _case_collision_id(corpus, relative)
                    conflicting = document_paths_by_id.get(document_id)
                    if conflicting is not None and conflicting != relative:
                        raise ValueError(f"Stable document ID collision between {conflicting!r} and {relative!r}")
                document_paths_by_id[document_id] = relative
                all_chunk_values = [chunk for _, _, _, _, chunks in page_values for chunk in chunks]
                document_text = "\n\n".join(text for _, text, _ in all_chunk_values)
                attributes: dict[str, Any] = {
                    "relative_path": relative,
                    "source_sha256": source_sha256,
                    "format": "pdf",
                    "page_count": page_count,
                    "text_pages": text_pages,
                    "image_only_pages": image_only_pages,
                    "blank_pages": blank_pages,
                    "searchable_page_ratio": searchable_ratio,
                    "pdf_author": _metadata_text(metadata, "/Author"),
                    "pdf_subject": _metadata_text(metadata, "/Subject"),
                    "pdf_keywords": _metadata_text(metadata, "/Keywords"),
                    "pdf_creator": _metadata_text(metadata, "/Creator"),
                    "pdf_producer": _metadata_text(metadata, "/Producer"),
                }
                attributes = {key: value for key, value in attributes.items() if value is not None}
                if case_collision:
                    attributes["case_distinct_path_collision"] = True
                document = CommonDocument(
                    document_id=document_id,
                    corpus=corpus,
                    title=title,
                    source_url=_source_url(relative, base_url=base_url, source_url_template=source_url_template),
                    source_version=source_version,
                    source_timestamp=source_timestamp,
                    license=license_name,
                    content_hash=make_content_id(document_text),
                    attributes=attributes,
                )
                documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                instance_ids = [
                    _instance_id(document_id, source_version, ordinal, heading, text)
                    for ordinal, (heading, text, _) in enumerate(all_chunk_values)
                ]
                for ordinal, ((heading, text, block_attributes), instance_id) in enumerate(
                    zip(all_chunk_values, instance_ids, strict=True)
                ):
                    chunk_attributes = dict(block_attributes)
                    chunk_attributes.update({"relative_path": relative, "section_index": ordinal, "chunk_index": ordinal})
                    chunk = CommonChunk(
                        chunk_instance_id=instance_id,
                        content_id=make_content_id(text),
                        document_id=document_id,
                        parent_chunk_id=None,
                        ordinal=ordinal,
                        heading_path=list(heading),
                        text=text,
                        character_count=len(text),
                        token_count=None,
                        previous_chunk_id=instance_ids[ordinal - 1] if ordinal else None,
                        next_chunk_id=instance_ids[ordinal + 1] if ordinal + 1 < len(instance_ids) else None,
                        attributes=chunk_attributes,
                    )
                    chunks_stream.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
                totals["documents"] += 1
                totals["chunks"] += len(all_chunk_values)
                totals["pages"] += page_count
                totals["text_pages"] += text_pages
                totals["image_only_pages"] += image_only_pages
                totals["blank_pages"] += blank_pages
                totals["source_bytes"] += before.st_size
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())

        if totals["documents"] == 0 or totals["chunks"] == 0:
            raise ValueError("PDF import produced no searchable records")
        files_manifest = {
            "documents": {"path": documents_path.name, "bytes": documents_path.stat().st_size, "sha256": _sha256(documents_path)},
            "chunks": {"path": chunks_path.name, "bytes": chunks_path.stat().st_size, "sha256": _sha256(chunks_path)},
        }
        complete_source = max_files is None or max_files >= len(all_files)
        finished = datetime.now(timezone.utc)
        stats = {
            "schema_version": 1,
            "output_schema_version": 1,
            "completed": complete_source,
            "stop_reason": "source_complete" if complete_source else "file_limit",
            "source_files": len(files),
            "available_source_files": len(all_files),
            **totals,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        manifest = {
            "schema_version": PDF_MANUAL_MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "importer": "pdf-manuals-v1",
            "corpus": corpus,
            "source_version": source_version,
            "source_timestamp": source_timestamp,
            "license": license_name,
            "base_url": base_url,
            "source_url_template": source_url_template,
            "completed": complete_source,
            "stop_reason": stats["stop_reason"],
            "counts": {"documents": totals["documents"], "chunks": totals["chunks"]},
            "page_counts": {
                "pages": totals["pages"],
                "text_pages": totals["text_pages"],
                "image_only_pages": totals["image_only_pages"],
                "blank_pages": totals["blank_pages"],
            },
            "configuration": {
                "max_chars": max_chars,
                "min_chars": min_chars,
                "min_searchable_ratio": min_searchable_ratio,
                "max_files": max_files,
                "ocr": False,
            },
            "parts": [{
                "part": 0,
                "documents": documents_path.name,
                "chunks": chunks_path.name,
                "documents_sha256": files_manifest["documents"]["sha256"],
                "chunks_sha256": files_manifest["chunks"]["sha256"],
            }],
            "files": files_manifest,
        }
        _atomic_json(temporary / "extraction-stats.json", stats)
        _atomic_json(temporary / "corpus-manifest.json", manifest)
        _publish_directory(temporary, output, force)
        return {
            "output": str(output.resolve()),
            "corpus": corpus,
            "source_version": source_version,
            **totals,
            "source_files": len(files),
        }
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import text-layer PDF manuals with page-aware citations.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--source-url-template")
    parser.add_argument("--source-timestamp")
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--min-searchable-ratio", type=float, default=0.5)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = import_pdf_manuals(
        args.source,
        args.output,
        corpus=args.corpus,
        source_version=args.source_version,
        license_name=args.license_name,
        base_url=args.base_url,
        source_url_template=args.source_url_template,
        source_timestamp=args.source_timestamp,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        min_searchable_ratio=args.min_searchable_ratio,
        max_files=args.max_files,
        force=args.force,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
