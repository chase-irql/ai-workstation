from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import zstandard

from .documentation import ContentBlock, chunk_blocks
from .records import CommonChunk, CommonDocument, make_content_id, normalize_content


MANIFEST_SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 1
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
SPACE_RE = re.compile(r"\s+")


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


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return SPACE_RE.sub(" ", "".join(element.itertext())).strip()


def _texts(element: ET.Element, path: str) -> list[str]:
    return [value for node in element.findall(path) if (value := _text(node))]


def _date(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    year = _text(element.find("Year"))
    month = _text(element.find("Month"))
    day = _text(element.find("Day"))
    medline = _text(element.find("MedlineDate"))
    if not year:
        return medline or None
    result = year
    if month:
        number = MONTHS.get(month[:3].casefold())
        result += f"-{number:02d}" if number else f"-{month}"
        if day:
            result += f"-{int(day):02d}" if day.isdigit() else f"-{day}"
    return result


def _first_date(article: ET.Element, paths: Sequence[str]) -> str | None:
    for path in paths:
        value = _date(article.find(path))
        if value:
            return value
    return None


def _authors(article: ET.Element) -> list[str]:
    values: list[str] = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            values.append(collective)
            continue
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName")) or _text(author.find("Initials"))
        name = ", ".join(part for part in (last, fore) if part)
        if name:
            values.append(name)
    return values


def _article_ids(article: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        value = _text(node)
        kind = (node.get("IdType") or "other").casefold()
        if value and kind not in values:
            values[kind] = value
    return values


def _mesh_terms(article: ET.Element) -> list[str]:
    values: list[str] = []
    for heading in article.findall(".//MeshHeadingList/MeshHeading"):
        descriptor = _text(heading.find("DescriptorName"))
        qualifiers = _texts(heading, "QualifierName")
        if descriptor:
            values.append(descriptor + (" / " + ", ".join(qualifiers) if qualifiers else ""))
    return values


def _abstract_blocks(article: ET.Element) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for index, node in enumerate(article.findall(".//Abstract/AbstractText")):
        value = _text(node)
        if not value:
            continue
        label = (node.get("Label") or node.get("NlmCategory") or "").strip()
        heading = ("Abstract", label) if label else ("Abstract",)
        blocks.append(ContentBlock(heading, value, "paragraph", {"abstract_section": index, "label": label or None}))
    return blocks


def _instance_id(document_id: str, source_version: str, ordinal: int, heading: Sequence[str], text: str) -> str:
    identity = json.dumps(
        [document_id, source_version, ordinal, list(heading), text],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _article_records(
    article: ET.Element,
    *,
    corpus: str,
    source_version: str,
    license_text: str,
    max_chars: int,
    min_chars: int,
) -> tuple[CommonDocument, list[CommonChunk]] | None:
    pmid_node = article.find(".//MedlineCitation/PMID")
    if pmid_node is None:
        pmid_node = article.find(".//BookDocument/PMID")
    pmid = _text(pmid_node)
    if not pmid:
        return None
    title = _text(article.find(".//ArticleTitle")) or _text(article.find(".//BookDocument/ArticleTitle"))
    title = title or f"PubMed record {pmid}"
    citation = article.find(".//MedlineCitation")
    identifiers = _article_ids(article)
    journal_title = _text(article.find(".//Journal/Title"))
    journal_iso = _text(article.find(".//Journal/ISOAbbreviation")) or _text(
        article.find(".//MedlineJournalInfo/MedlineTA")
    )
    publication_date = _first_date(
        article,
        (
            ".//ArticleDate",
            ".//JournalIssue/PubDate",
            ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']",
            ".//PubmedData/History/PubMedPubDate[@PubStatus='entrez']",
        ),
    )
    revised_date = _first_date(article, (".//MedlineCitation/DateRevised", ".//DateCompleted"))
    authors = _authors(article)
    mesh = _mesh_terms(article)
    keywords = _texts(article, ".//KeywordList/Keyword")
    publication_types = _texts(article, ".//PublicationTypeList/PublicationType")
    chemicals = _texts(article, ".//ChemicalList/Chemical/NameOfSubstance")
    languages = _texts(article, ".//Article/Language") or _texts(article, ".//BookDocument/Language")
    volume = _text(article.find(".//JournalIssue/Volume"))
    issue = _text(article.find(".//JournalIssue/Issue"))
    pages = _text(article.find(".//Pagination/MedlinePgn"))
    blocks = _abstract_blocks(article)
    metadata_lines = []
    if mesh:
        metadata_lines.append("MeSH terms: " + "; ".join(mesh))
    if keywords:
        metadata_lines.append("Keywords: " + "; ".join(keywords))
    if publication_types:
        metadata_lines.append("Publication types: " + "; ".join(publication_types))
    if chemicals:
        metadata_lines.append("Chemicals: " + "; ".join(chemicals))
    if metadata_lines:
        blocks.append(ContentBlock(("Indexing",), "\n".join(metadata_lines), "metadata", {}))
    if not blocks:
        fallback = ". ".join(
            value for value in (
                title,
                f"Journal: {journal_title or journal_iso}" if journal_title or journal_iso else "",
                f"Authors: {'; '.join(authors)}" if authors else "",
                f"Publication date: {publication_date}" if publication_date else "",
            ) if value
        )
        blocks.append(ContentBlock(("Citation",), fallback, "metadata", {}))
    values = chunk_blocks(blocks, max_chars, min_chars)
    document_id = f"{corpus}:pmid:{pmid}"
    source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    status = citation.get("Status") if citation is not None else None
    owner = citation.get("Owner") if citation is not None else None
    attributes: dict[str, Any] = {
        "pmid": pmid,
        "pmid_version": pmid_node.get("Version") if pmid_node is not None else None,
        "record_status": status,
        "record_owner": owner,
        "identifiers": identifiers,
        "doi": identifiers.get("doi"),
        "pmcid": identifiers.get("pmc"),
        "journal_title": journal_title or None,
        "journal_abbreviation": journal_iso or None,
        "issn": _text(article.find(".//Journal/ISSN")) or None,
        "volume": volume or None,
        "issue": issue or None,
        "pages": pages or None,
        "publication_date": publication_date,
        "authors": authors,
        "languages": languages,
        "publication_types": publication_types,
        "mesh_terms": mesh,
        "keywords": keywords,
        "chemicals": chemicals,
    }
    content_text = normalize_content("\n\n".join(text for _, text, _ in values))
    document = CommonDocument(
        document_id=document_id,
        corpus=corpus,
        title=title,
        source_url=source_url,
        source_version=source_version,
        source_timestamp=revised_date or publication_date,
        license=license_text,
        content_hash=make_content_id(content_text),
        attributes=attributes,
    )
    ids = [
        _instance_id(document_id, source_version, ordinal, heading, text)
        for ordinal, (heading, text, _) in enumerate(values)
    ]
    chunks: list[CommonChunk] = []
    for ordinal, ((heading, text, block_attributes), instance_id) in enumerate(zip(values, ids, strict=True)):
        chunks.append(
            CommonChunk(
                chunk_instance_id=instance_id,
                content_id=make_content_id(text),
                document_id=document_id,
                parent_chunk_id=None,
                ordinal=ordinal,
                heading_path=list(heading),
                text=text,
                character_count=len(text),
                token_count=None,
                previous_chunk_id=ids[ordinal - 1] if ordinal else None,
                next_chunk_id=ids[ordinal + 1] if ordinal + 1 < len(ids) else None,
                attributes={
                    "pmid": pmid,
                    "doi": identifiers.get("doi"),
                    "pmcid": identifiers.get("pmc"),
                    "journal": journal_title or journal_iso or None,
                    "publication_date": publication_date,
                    "section_index": ordinal,
                    "chunk_index": ordinal,
                    "source_url": source_url,
                    **block_attributes,
                },
            )
        )
    return document, chunks


def _iter_articles(path: Path) -> Iterator[ET.Element]:
    try:
        with gzip.open(path, "rb") as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag.rsplit("}", 1)[-1] in {"PubmedArticle", "PubmedBookArticle"}:
                    yield element
                    element.clear()
    except (gzip.BadGzipFile, EOFError, ET.ParseError) as error:
        raise ValueError(f"Invalid PubMed gzip/XML input: {path}") from error


def _open_zstd_text(path: Path, level: int) -> tuple[BinaryIO, BinaryIO, TextIO]:
    raw = path.open("xb")
    writer = zstandard.ZstdCompressor(level=level).stream_writer(raw, closefd=False)
    text = __import__("io").TextIOWrapper(writer, encoding="utf-8", newline="\n")
    return raw, writer, text


def _close_zstd_text(raw: BinaryIO, writer: BinaryIO, text: TextIO) -> None:
    text.flush()
    text.detach()
    writer.close()
    raw.flush()
    os.fsync(raw.fileno())
    raw.close()


def _source_manifest(source_root: Path, corpus: str) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    path = source_root / "acquisition-manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Validated acquisition manifest not found: {path}")
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("status") != "validated" or manifest.get("dataset_id") != corpus:
        raise ValueError("PubMed source must have a validated, matching acquisition manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("PubMed acquisition manifest contains no files")
    ordered = sorted(files, key=lambda item: str(item.get("relative_path") or item.get("filename")))
    for item in ordered:
        relative = str(item.get("relative_path") or item.get("filename") or "")
        if not re.fullmatch(r"pubmed\d+n\d{4}\.xml\.gz", relative):
            raise ValueError(f"Unexpected PubMed source filename: {relative!r}")
        path_value = (source_root / "files" / relative).resolve()
        if not path_value.is_relative_to((source_root / "files").resolve()) or not path_value.is_file():
            raise FileNotFoundError(path_value)
        if path_value.stat().st_size != int(item["bytes"]):
            raise ValueError(f"PubMed source size no longer matches acquisition manifest: {relative}")
    return manifest, hashlib.sha256(raw).hexdigest(), ordered


def _configuration_fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_completed_parts(building: Path, parts: Sequence[dict[str, Any]]) -> None:
    """Validate every checkpointed shard before trusting it during resume."""

    root = building.resolve()
    seen_sources: set[str] = set()
    seen_parts: set[int] = set()
    for part in parts:
        source = str(part.get("source") or "")
        part_number = int(part.get("part", -1))
        if not source or source in seen_sources or part_number < 0 or part_number in seen_parts:
            raise ValueError("PubMed checkpoint contains duplicate or invalid completed parts")
        seen_sources.add(source)
        seen_parts.add(part_number)
        for prefix in ("documents", "chunks"):
            path = (building / str(part[prefix])).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise FileNotFoundError(f"Checkpointed PubMed shard is missing or unsafe: {path}")
            if path.stat().st_size != int(part[f"{prefix}_bytes"]):
                raise ValueError(f"Checkpointed PubMed shard size changed: {path}")
            if _sha256(path) != str(part[f"{prefix}_sha256"]):
                raise ValueError(f"Checkpointed PubMed shard checksum changed: {path}")


def _write_part(
    source: Path,
    part_directory: Path,
    part_number: int,
    *,
    corpus: str,
    source_version: str,
    license_text: str,
    max_chars: int,
    min_chars: int,
    zstd_level: int,
) -> dict[str, Any]:
    stem = f"part-{part_number:04d}"
    documents_name = f"parts/{stem}.documents.jsonl.zst"
    chunks_name = f"parts/{stem}.chunks.jsonl.zst"
    documents_path = part_directory.parent / documents_name
    chunks_path = part_directory.parent / chunks_name
    documents_temp = documents_path.with_suffix(documents_path.suffix + ".partial")
    chunks_temp = chunks_path.with_suffix(chunks_path.suffix + ".partial")
    for path in (documents_temp, chunks_temp):
        if path.exists():
            path.unlink()
    documents_raw = documents_writer = documents_text = None
    chunks_raw = chunks_writer = chunks_text = None
    documents = chunks = skipped = 0
    try:
        documents_raw, documents_writer, documents_text = _open_zstd_text(documents_temp, zstd_level)
        chunks_raw, chunks_writer, chunks_text = _open_zstd_text(chunks_temp, zstd_level)
        for element in _iter_articles(source):
            result = _article_records(
                element,
                corpus=corpus,
                source_version=source_version,
                license_text=license_text,
                max_chars=max_chars,
                min_chars=min_chars,
            )
            if result is None:
                skipped += 1
                continue
            document, article_chunks = result
            documents_text.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
            for chunk in article_chunks:
                chunks_text.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
            documents += 1
            chunks += len(article_chunks)
        _close_zstd_text(documents_raw, documents_writer, documents_text)
        documents_raw = documents_writer = documents_text = None
        _close_zstd_text(chunks_raw, chunks_writer, chunks_text)
        chunks_raw = chunks_writer = chunks_text = None
        if documents == 0 or chunks == 0:
            raise ValueError(f"PubMed source shard produced no searchable records: {source.name}")
        os.replace(documents_temp, documents_path)
        os.replace(chunks_temp, chunks_path)
        return {
            "part": part_number,
            "source": source.name,
            "documents": documents_name,
            "chunks": chunks_name,
            "document_count": documents,
            "chunk_count": chunks,
            "skipped_records": skipped,
            "documents_bytes": documents_path.stat().st_size,
            "chunks_bytes": chunks_path.stat().st_size,
            "documents_sha256": _sha256(documents_path),
            "chunks_sha256": _sha256(chunks_path),
        }
    except BaseException:
        for text in (documents_text, chunks_text):
            if text is not None:
                try:
                    text.close()
                except Exception:
                    pass
        for raw in (documents_raw, chunks_raw):
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass
        for path in (documents_temp, chunks_temp):
            if path.exists():
                path.unlink()
        raise


def _publish_directory(building: Path, output: Path, force: bool) -> None:
    if not output.exists():
        os.replace(building, output)
        return
    if not force or not output.is_dir():
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized PubMed output")
    manifest_path = output / "corpus-manifest.json"
    if not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")).get("importer") != "pubmed":
        raise ValueError(f"Refusing to replace unrecognized output directory: {output}")
    backup = output.with_name(f".{output.name}.replaced-{uuid.uuid4().hex}")
    os.replace(output, backup)
    try:
        os.replace(building, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def import_pubmed(
    source_root: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    license_text: str,
    max_chars: int = 3200,
    min_chars: int = 200,
    zstd_level: int = 6,
    workers: int = 1,
    max_files: int | None = None,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Stream a validated PubMed baseline into resumable compressed shards."""

    if not source_root.is_dir() or not corpus or not source_version or not license_text:
        raise ValueError("A source directory, corpus, source version, and license are required")
    if max_chars < 128 or min_chars < 0 or min_chars > max_chars:
        raise ValueError("max_chars must be at least 128 and min_chars must be between zero and max_chars")
    if not 1 <= zstd_level <= 19 or not 1 <= workers <= 32 or (max_files is not None and max_files <= 0):
        raise ValueError("zstd_level must be 1..19, workers 1..32, and max_files positive when supplied")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized PubMed output")
    _, acquisition_sha256, source_files = _source_manifest(source_root, corpus)
    configuration = {
        "corpus": corpus,
        "source_version": source_version,
        "license": license_text,
        "max_chars": max_chars,
        "min_chars": min_chars,
        "zstd_level": zstd_level,
        "acquisition_manifest_sha256": acquisition_sha256,
    }
    fingerprint = _configuration_fingerprint(configuration)
    output.parent.mkdir(parents=True, exist_ok=True)
    building = output.parent / f".{output.name}.pubmed-building"
    checkpoint_path = building / "checkpoint.json"
    if building.exists():
        if not checkpoint_path.is_file():
            raise ValueError(f"Refusing unrecognized PubMed build directory: {building}")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION or checkpoint.get("fingerprint") != fingerprint:
            raise ValueError("PubMed checkpoint does not match the source or import configuration")
        if not isinstance(checkpoint.get("parts"), list):
            raise ValueError("PubMed checkpoint parts must be an array")
        _validate_completed_parts(building, checkpoint["parts"])
    else:
        building.mkdir()
        (building / "parts").mkdir()
        checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "importer": "pubmed",
            "fingerprint": fingerprint,
            "configuration": configuration,
            "completed": False,
            "stop_reason": None,
            "parts": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(checkpoint_path, checkpoint)
    completed_sources = {str(part["source"]) for part in checkpoint["parts"]}
    if progress is not None:
        progress(
            {
                "event": "pubmed_import_progress",
                "completed_files": len(checkpoint["parts"]),
                "total_files": len(source_files),
                "documents": sum(int(part["document_count"]) for part in checkpoint["parts"]),
                "chunks": sum(int(part["chunk_count"]) for part in checkpoint["parts"]),
            }
        )
    remaining: list[tuple[int, str]] = []
    for part_number, source_item in enumerate(source_files):
        source_name = str(source_item.get("relative_path") or source_item["filename"])
        if source_name not in completed_sources:
            remaining.append((part_number, source_name))
    selected = remaining[:max_files] if max_files is not None else remaining

    def record_part(part: dict[str, Any]) -> None:
        checkpoint["parts"].append(part)
        checkpoint["stop_reason"] = None
        _atomic_json(checkpoint_path, checkpoint)
        if progress is not None:
            progress(
                {
                    "event": "pubmed_import_progress",
                    "completed_files": len(checkpoint["parts"]),
                    "total_files": len(source_files),
                    "documents": sum(int(value["document_count"]) for value in checkpoint["parts"]),
                    "chunks": sum(int(value["chunk_count"]) for value in checkpoint["parts"]),
                }
            )

    arguments = {
        "corpus": corpus,
        "source_version": source_version,
        "license_text": license_text,
        "max_chars": max_chars,
        "min_chars": min_chars,
        "zstd_level": zstd_level,
    }
    if workers == 1:
        for part_number, source_name in selected:
            record_part(
                _write_part(
                    source_root / "files" / source_name,
                    building / "parts",
                    part_number,
                    **arguments,
                )
            )
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _write_part,
                    source_root / "files" / source_name,
                    building / "parts",
                    part_number,
                    **arguments,
                ): source_name
                for part_number, source_name in selected
            }
            for future in as_completed(futures):
                record_part(future.result())

    if max_files is not None and len(checkpoint["parts"]) < len(source_files):
        checkpoint["stop_reason"] = "file_limit"
        _atomic_json(checkpoint_path, checkpoint)
        return {
            "output": str(output.resolve()),
            "completed": False,
            "stop_reason": "file_limit",
            "parts": len(checkpoint["parts"]),
            "documents": sum(int(part["document_count"]) for part in checkpoint["parts"]),
            "chunks": sum(int(part["chunk_count"]) for part in checkpoint["parts"]),
        }
    parts = sorted(checkpoint["parts"], key=lambda item: int(item["part"]))
    documents = sum(int(part["document_count"]) for part in parts)
    chunks = sum(int(part["chunk_count"]) for part in parts)
    skipped = sum(int(part["skipped_records"]) for part in parts)
    finished = datetime.now(timezone.utc).isoformat()
    checkpoint.update({"completed": True, "stop_reason": "source_complete", "finished_at": finished})
    _atomic_json(checkpoint_path, checkpoint)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "importer": "pubmed",
        "record_format": "offline-rag-common-jsonl-v1",
        "record_schema_version": 1,
        "corpus": corpus,
        "source_version": source_version,
        "license": license_text,
        "base_url": "https://pubmed.ncbi.nlm.nih.gov/",
        "completed": True,
        "stop_reason": "source_complete",
        "counts": {"documents": documents, "chunks": chunks, "skipped_records": skipped},
        "configuration": configuration,
        "source_acquisition_manifest_sha256": acquisition_sha256,
        "parts": parts,
    }
    stats = {
        "schema_version": 1,
        "completed": True,
        "stop_reason": "source_complete",
        "documents": documents,
        "chunks": chunks,
        "skipped_records": skipped,
        "source_files": len(source_files),
        "started_at": checkpoint["started_at"],
        "finished_at": finished,
    }
    _atomic_json(building / "corpus-manifest.json", manifest)
    _atomic_json(building / "extraction-stats.json", stats)
    _publish_directory(building, output, force)
    return {"output": str(output.resolve()), **stats}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream a validated PubMed baseline into common compressed shards.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license", dest="license_text", required=True)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--min-chars", type=int, default=200)
    parser.add_argument("--zstd-level", type=int, default=6)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    def report(value: dict[str, Any]) -> None:
        print("PUBMED_PROGRESS " + json.dumps(value, sort_keys=True), flush=True)

    result = import_pubmed(**vars(build_parser().parse_args(argv)), progress=report)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("completed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
