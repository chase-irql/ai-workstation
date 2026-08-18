from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import mwparserfromhell


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
MEDIA_NAMESPACES = {"file", "image", "category"}
REMOVED_TAGS = {"gallery", "ref"}


@dataclass(frozen=True)
class Document:
    document_id: str
    source: str
    dump_date: str
    article_id: int
    revision_id: int | None
    revision_timestamp: str | None
    title: str
    source_url: str
    redirect_target: str | None


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    source: str
    dump_date: str
    article_id: int
    revision_id: int | None
    revision_timestamp: str | None
    title: str
    source_url: str
    section_index: int
    chunk_index: int
    heading_path: list[str]
    text: str
    content_hash: str


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element if local_name(item.tag) == name), None)


def child_text(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    item = child(element, name)
    return item.text if item is not None else None


def article_url(title: str) -> str:
    slug = urllib.parse.quote(title.replace(" ", "_"), safe="()_-!~*',")
    return f"https://en.wikipedia.org/wiki/{slug}"


def clean_wikicode(value: object) -> str:
    code = mwparserfromhell.parse(str(value))
    for link in list(code.filter_wikilinks(recursive=True)):
        namespace = str(link.title).strip().partition(":")[0].casefold()
        if namespace in MEDIA_NAMESPACES:
            try:
                code.remove(link, recursive=True)
            except ValueError:
                pass
    for tag in list(code.filter_tags(recursive=True)):
        if str(tag.tag).strip().casefold() in REMOVED_TAGS:
            try:
                code.remove(tag, recursive=True)
            except ValueError:
                pass
    text = code.strip_code(normalize=True, collapse=False)
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized:
            paragraphs.append(normalized)
    return "\n\n".join(paragraphs)


def iter_sections(wikitext: str) -> Iterator[tuple[list[str], str]]:
    code = mwparserfromhell.parse(wikitext)
    stack: list[str] = []
    heading_path: list[str] = []
    nodes = []
    for node in code.nodes:
        if not isinstance(node, mwparserfromhell.nodes.Heading):
            nodes.append(node)
            continue
        body = clean_wikicode(mwparserfromhell.wikicode.Wikicode(nodes))
        if body:
            yield heading_path, body
        heading = clean_wikicode(node.title) or str(node.title).strip()
        stack = stack[: max(0, node.level - 2)]
        stack.append(heading)
        heading_path = list(stack)
        nodes = []
    body = clean_wikicode(mwparserfromhell.wikicode.Wikicode(nodes))
    if body:
        yield heading_path, body


def split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = SENTENCE_RE.split(text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(sentence[offset : offset + max_chars] for offset in range(0, len(sentence), max_chars))
        elif not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            parts.append(current)
            current = sentence
    if current:
        parts.append(current)
    return parts


def chunk_section(text: str, max_chars: int = 3200, min_chars: int = 40) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for part in split_long_text(paragraph, max_chars):
            if not current:
                current = part
            elif len(current) + 2 + len(part) <= max_chars:
                current = f"{current}\n\n{part}"
            else:
                chunks.append(current)
                current = part
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if len(chunk) >= min_chars]


def page_records(page: ET.Element, dump_date: str, max_chars: int) -> tuple[Document | None, list[Chunk]]:
    namespace_text = child_text(page, "ns")
    if namespace_text != "0":
        return None, []
    title = child_text(page, "title") or ""
    article_id_text = child_text(page, "id")
    if not article_id_text:
        return None, []
    article_id = int(article_id_text)
    redirect_element = child(page, "redirect")
    redirect_target = redirect_element.attrib.get("title") if redirect_element is not None else None
    revision = child(page, "revision")
    revision_id_text = child_text(revision, "id")
    revision_id = int(revision_id_text) if revision_id_text else None
    revision_timestamp = child_text(revision, "timestamp")
    text_element = child(revision, "text") if revision is not None else None
    wikitext = text_element.text if text_element is not None and text_element.text else ""
    document_id = f"enwiki:{article_id}"
    url = article_url(title)
    document = Document(
        document_id=document_id,
        source="wikipedia-en",
        dump_date=dump_date,
        article_id=article_id,
        revision_id=revision_id,
        revision_timestamp=revision_timestamp,
        title=title,
        source_url=url,
        redirect_target=redirect_target,
    )
    if redirect_target:
        return document, []

    chunks: list[Chunk] = []
    for section_index, (heading_path, section_text) in enumerate(iter_sections(wikitext)):
        for chunk_index, text in enumerate(chunk_section(section_text, max_chars=max_chars)):
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            identity = f"{document_id}:{revision_id}:{section_index}:{chunk_index}:{content_hash}"
            chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source="wikipedia-en",
                    dump_date=dump_date,
                    article_id=article_id,
                    revision_id=revision_id,
                    revision_timestamp=revision_timestamp,
                    title=title,
                    source_url=url,
                    section_index=section_index,
                    chunk_index=chunk_index,
                    heading_path=heading_path,
                    text=text,
                    content_hash=content_hash,
                )
            )
    return document, chunks


def iter_pages(archive: Path) -> Iterator[ET.Element]:
    with bz2.open(archive, "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        _, root = next(context)
        for event, element in context:
            if event == "end" and local_name(element.tag) == "page":
                yield element
                element.clear()
                root.clear()


def write_json_line(stream, value: object) -> None:
    line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    stream.write(line.encode("utf-8"))


def save_checkpoint(
    checkpoint_path: Path,
    archive: Path,
    dump_date: str,
    max_chars: int,
    document_count: int,
    redirect_count: int,
    chunk_count: int,
    documents,
    chunks,
    completed: bool,
) -> None:
    documents.flush()
    chunks.flush()
    os.fsync(documents.fileno())
    os.fsync(chunks.fileno())
    state = {
        "schema_version": 1,
        "archive": str(archive.resolve()),
        "archive_size": archive.stat().st_size,
        "dump_date": dump_date,
        "max_chunk_characters": max_chars,
        "documents": document_count,
        "redirects": redirect_count,
        "chunks": chunk_count,
        "documents_offset": documents.tell(),
        "chunks_offset": chunks.tell(),
        "completed": completed,
    }
    temporary_path = checkpoint_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary_path.replace(checkpoint_path)


def load_checkpoint(checkpoint_path: Path, archive: Path, dump_date: str, max_chars: int) -> dict[str, object]:
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Resume checkpoint not found: {checkpoint_path}")
    state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1,
        "archive": str(archive.resolve()),
        "archive_size": archive.stat().st_size,
        "dump_date": dump_date,
        "max_chunk_characters": max_chars,
    }
    for key, value in expected.items():
        if state.get(key) != value:
            raise ValueError(f"Checkpoint {key} mismatch: expected {value!r}, found {state.get(key)!r}")
    return state


def extract(
    archive: Path,
    output: Path,
    dump_date: str,
    max_articles: int | None,
    max_chars: int,
    resume: bool = False,
    checkpoint_interval: int = 1000,
) -> dict[str, object]:
    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    output.mkdir(parents=True, exist_ok=True)
    documents_path = output / "documents.jsonl"
    chunks_path = output / "chunks.jsonl"
    checkpoint_path = output / "checkpoint.json"
    started = time.monotonic()
    document_count = 0
    redirect_count = 0
    chunk_count = 0
    resumed_from_documents = 0
    mode = "wb"

    if resume:
        state = load_checkpoint(checkpoint_path, archive=archive, dump_date=dump_date, max_chars=max_chars)
        document_count = int(state["documents"])
        redirect_count = int(state["redirects"])
        chunk_count = int(state["chunks"])
        resumed_from_documents = document_count
        mode = "r+b"
        if not documents_path.exists() or not chunks_path.exists():
            raise FileNotFoundError("Resume output files are missing")

    with documents_path.open(mode) as documents, chunks_path.open(mode) as chunks:
        if resume:
            documents.truncate(int(state["documents_offset"]))
            chunks.truncate(int(state["chunks_offset"]))
            documents.seek(0, os.SEEK_END)
            chunks.seek(0, os.SEEK_END)

        remaining_to_skip = resumed_from_documents
        for page in iter_pages(archive):
            if remaining_to_skip:
                if child_text(page, "ns") == "0" and child_text(page, "id"):
                    remaining_to_skip -= 1
                continue
            document, page_chunks = page_records(page, dump_date=dump_date, max_chars=max_chars)
            if document is None:
                continue
            write_json_line(documents, asdict(document))
            document_count += 1
            if document.redirect_target:
                redirect_count += 1
            for chunk in page_chunks:
                write_json_line(chunks, asdict(chunk))
                chunk_count += 1
            if document_count % checkpoint_interval == 0:
                save_checkpoint(
                    checkpoint_path,
                    archive,
                    dump_date,
                    max_chars,
                    document_count,
                    redirect_count,
                    chunk_count,
                    documents,
                    chunks,
                    completed=False,
                )
                print(f"extracted documents={document_count} chunks={chunk_count}", file=sys.stderr, flush=True)
            if max_articles is not None and document_count >= max_articles:
                break

        if remaining_to_skip:
            raise ValueError(f"Archive ended before {resumed_from_documents} checkpointed documents were found")
        save_checkpoint(
            checkpoint_path,
            archive,
            dump_date,
            max_chars,
            document_count,
            redirect_count,
            chunk_count,
            documents,
            chunks,
            completed=True,
        )

    stats = {
        "schema_version": 1,
        "dump_date": dump_date,
        "archive": str(archive.resolve()),
        "documents": document_count,
        "redirects": redirect_count,
        "chunks": chunk_count,
        "max_chunk_characters": max_chars,
        "resumed_from_documents": resumed_from_documents,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    (output / "extraction-stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream and structurally chunk a MediaWiki articles dump.")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dump-date", required=True)
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-interval", type=int, default=1000)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stats = extract(
        archive=args.archive,
        output=args.output,
        dump_date=args.dump_date,
        max_articles=args.max_articles,
        max_chars=args.max_chars,
        resume=args.resume,
        checkpoint_interval=args.checkpoint_interval,
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
