from __future__ import annotations

import argparse
import bz2
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

import zstandard

from .wikipedia_dump import archive_identity, atomic_write_json, page_records, write_json_line


PLAN_SCHEMA_VERSION = 1
SHARD_SCHEMA_VERSION = 1
OUTPUT_SCHEMA_VERSION = 2
PAGE_PATTERN = re.compile(br"<page(?:\s[^>]*)?>.*?</page>", re.DOTALL)
DEFAULT_BATCH_BLOCKS = 128
DEFAULT_TARGET_PART_MIB = 8
DEFAULT_WORKERS = max(1, min(8, os.cpu_count() or 1))
DEFAULT_ZSTD_LEVEL = 3
# The distributed 2026-08 English Wikipedia sample measured 2,754 bytes/chunk.
# Keep a conservative margin for corpus variation and SQLite page allocation.
DEFAULT_SQLITE_BYTES_PER_CHUNK = 3000


class ParallelExtractionInterrupted(RuntimeError):
    """Raised after accepting no new work and preserving completed shards."""


@dataclass(frozen=True)
class StreamBlock:
    ordinal: int
    start: int
    end: int
    pages: int


@dataclass(frozen=True)
class WorkPart:
    ordinal: int
    blocks: tuple[StreamBlock, ...]

    @property
    def first_block(self) -> int:
        return self.blocks[0].ordinal

    @property
    def last_block(self) -> int:
        return self.blocks[-1].ordinal


def _file_identity(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def iter_stream_blocks(index: Path, archive_size: int) -> Iterator[StreamBlock]:
    """Yield independently decompressible blocks described by a Wikimedia index."""

    if not index.is_file():
        raise FileNotFoundError(f"Multistream index is not a regular file: {index}")
    current_offset: int | None = None
    current_pages = 0
    ordinal = 0
    with bz2.open(index, "rt", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                offset_text, page_id, _title = line.rstrip("\n").split(":", 2)
                offset = int(offset_text)
                int(page_id)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid multistream index line {line_number}") from error
            if offset < 0 or offset >= archive_size:
                raise ValueError(f"Index offset outside archive at line {line_number}: {offset}")
            if current_offset is None:
                current_offset = offset
                current_pages = 1
                continue
            if offset < current_offset:
                raise ValueError(f"Index offsets are not ordered at line {line_number}")
            if offset == current_offset:
                current_pages += 1
                continue
            yield StreamBlock(ordinal=ordinal, start=current_offset, end=offset, pages=current_pages)
            ordinal += 1
            current_offset = offset
            current_pages = 1
    if current_offset is None:
        raise ValueError("Multistream index contains no page entries")
    yield StreamBlock(ordinal=ordinal, start=current_offset, end=archive_size, pages=current_pages)


def build_plan(
    archive: Path,
    index: Path,
    plan_path: Path,
    dump_date: str,
    max_chars: int,
    batch_blocks: int,
    target_part_mib: int,
) -> dict[str, object]:
    if not archive.is_file():
        raise FileNotFoundError(f"Archive is not a regular file: {archive}")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if batch_blocks < 1 or target_part_mib < 1:
        raise ValueError("batch_blocks and target_part_mib must be positive")
    blocks = list(iter_stream_blocks(index, archive.stat().st_size))
    value: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "created_at_unix": int(time.time()),
        "archive_identity": archive_identity(archive),
        "index_identity": _file_identity(index),
        "configuration": {
            "dump_date": dump_date,
            "max_chunk_characters": max_chars,
            "batch_blocks": batch_blocks,
            "target_part_mib": target_part_mib,
            "namespace": 0,
            "chunker": "wikipedia-structural-v1",
            "compression": "zstd",
        },
        "block_count": len(blocks),
        "indexed_page_count": sum(block.pages for block in blocks),
        "blocks": [asdict(block) for block in blocks],
    }
    atomic_write_json(plan_path, value)
    return value


def load_plan(
    archive: Path,
    index: Path,
    plan_path: Path,
    dump_date: str,
    max_chars: int,
    batch_blocks: int,
    target_part_mib: int,
) -> dict[str, object]:
    value = json.loads(plan_path.read_text(encoding="utf-8"))
    if value.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("Unsupported multistream plan schema")
    expected_archive = archive_identity(archive)
    found_archive = value.get("archive_identity")
    if not isinstance(found_archive, Mapping):
        raise ValueError("Plan archive identity is missing")
    for key in ("path", "bytes", "sha1", "manifest_sha256", "mtime_ns"):
        if key in expected_archive and found_archive.get(key) != expected_archive[key]:
            raise ValueError(f"Plan archive identity mismatch for {key}")
    expected_index = _file_identity(index)
    found_index = value.get("index_identity")
    if not isinstance(found_index, Mapping):
        raise ValueError("Plan index identity is missing")
    for key, expected in expected_index.items():
        if found_index.get(key) != expected:
            raise ValueError(f"Plan index identity mismatch for {key}")
    expected_configuration = {
        "dump_date": dump_date,
        "max_chunk_characters": max_chars,
        "batch_blocks": batch_blocks,
        "target_part_mib": target_part_mib,
        "namespace": 0,
        "chunker": "wikipedia-structural-v1",
        "compression": "zstd",
    }
    if value.get("configuration") != expected_configuration:
        raise ValueError("Plan extraction configuration mismatch")
    blocks = value.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != value.get("block_count"):
        raise ValueError("Plan block list is inconsistent")
    return value


def plan_blocks(value: Mapping[str, object]) -> list[StreamBlock]:
    raw_blocks = value.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError("Plan blocks are missing")
    blocks = [StreamBlock(**item) for item in raw_blocks]
    for expected, block in enumerate(blocks):
        if block.ordinal != expected or block.end <= block.start or block.pages < 1:
            raise ValueError(f"Invalid planned block {expected}")
    return blocks


def work_parts(
    blocks: Sequence[StreamBlock], batch_blocks: int, target_part_bytes: int
) -> list[WorkPart]:
    """Group adjacent blocks by compressed bytes with a hard block-count ceiling."""

    parts: list[WorkPart] = []
    current: list[StreamBlock] = []
    current_bytes = 0
    for block in blocks:
        block_bytes = block.end - block.start
        if current and (
            len(current) >= batch_blocks or current_bytes + block_bytes > target_part_bytes
        ):
            parts.append(WorkPart(ordinal=len(parts), blocks=tuple(current)))
            current = []
            current_bytes = 0
        current.append(block)
        current_bytes += block_bytes
    if current:
        parts.append(WorkPart(ordinal=len(parts), blocks=tuple(current)))
    return parts


def _page_elements(fragment: bytes, block: StreamBlock) -> Iterator[Any]:
    import xml.etree.ElementTree as ET

    matches = list(PAGE_PATTERN.finditer(fragment))
    if len(matches) != block.pages:
        raise ValueError(
            f"Block {block.ordinal} contains {len(matches)} XML pages; index expects {block.pages}"
        )
    for match in matches:
        try:
            yield ET.fromstring(match.group(0))
        except ET.ParseError as error:
            raise ValueError(f"Invalid page XML in block {block.ordinal}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_zstd_writer(path: Path, level: int) -> tuple[BinaryIO, BinaryIO]:
    raw = path.open("xb")
    writer = zstandard.ZstdCompressor(level=level).stream_writer(raw, closefd=False)
    return raw, writer


def _finish_zstd_writer(raw: BinaryIO, writer: BinaryIO) -> None:
    writer.close()
    raw.flush()
    os.fsync(raw.fileno())
    raw.close()


def extract_part(
    archive_text: str,
    output_text: str,
    part: WorkPart,
    dump_date: str,
    max_chars: int,
    zstd_level: int,
) -> dict[str, object]:
    """Worker entry point. It writes only files owned by the supplied part."""

    archive = Path(archive_text)
    parts_directory = Path(output_text) / "parts"
    stem = f"part-{part.ordinal:06d}"
    documents_name = f"{stem}.documents.jsonl.zst"
    chunks_name = f"{stem}.chunks.jsonl.zst"
    manifest_name = f"{stem}.manifest.json"
    documents_path = parts_directory / documents_name
    chunks_path = parts_directory / chunks_name
    manifest_path = parts_directory / manifest_name
    token = f".tmp-{os.getpid()}"
    documents_temporary = documents_path.with_name(documents_path.name + token)
    chunks_temporary = chunks_path.with_name(chunks_path.name + token)
    documents_raw: BinaryIO | None = None
    chunks_raw: BinaryIO | None = None
    documents_writer: BinaryIO | None = None
    chunks_writer: BinaryIO | None = None
    document_count = redirect_count = chunk_count = page_count = uncompressed_bytes = 0
    started = time.monotonic()
    try:
        documents_raw, documents_writer = _open_zstd_writer(documents_temporary, zstd_level)
        chunks_raw, chunks_writer = _open_zstd_writer(chunks_temporary, zstd_level)
        with archive.open("rb") as source:
            for block in part.blocks:
                source.seek(block.start)
                compressed = source.read(block.end - block.start)
                if len(compressed) != block.end - block.start:
                    raise EOFError(f"Short read for block {block.ordinal}")
                try:
                    fragment = bz2.decompress(compressed)
                except OSError as error:
                    raise ValueError(f"Cannot decompress block {block.ordinal}") from error
                uncompressed_bytes += len(fragment)
                for page in _page_elements(fragment, block):
                    page_count += 1
                    document, page_chunks = page_records(page, dump_date=dump_date, max_chars=max_chars)
                    if document is None:
                        continue
                    write_json_line(documents_writer, asdict(document))
                    document_count += 1
                    if document.redirect_target:
                        redirect_count += 1
                    for chunk in page_chunks:
                        write_json_line(chunks_writer, asdict(chunk))
                        chunk_count += 1
        _finish_zstd_writer(documents_raw, documents_writer)
        documents_raw = documents_writer = None
        _finish_zstd_writer(chunks_raw, chunks_writer)
        chunks_raw = chunks_writer = None
        os.replace(documents_temporary, documents_path)
        os.replace(chunks_temporary, chunks_path)
        manifest: dict[str, object] = {
            "schema_version": SHARD_SCHEMA_VERSION,
            "part": part.ordinal,
            "first_block": part.first_block,
            "last_block": part.last_block,
            "block_count": len(part.blocks),
            "indexed_pages": page_count,
            "documents": document_count,
            "redirects": redirect_count,
            "chunks": chunk_count,
            "uncompressed_xml_bytes": uncompressed_bytes,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "files": {
                "documents": {
                    "name": documents_name,
                    "bytes": documents_path.stat().st_size,
                    "sha256": _sha256(documents_path),
                },
                "chunks": {
                    "name": chunks_name,
                    "bytes": chunks_path.stat().st_size,
                    "sha256": _sha256(chunks_path),
                },
            },
        }
        atomic_write_json(manifest_path, manifest)
        return manifest
    except BaseException:
        for writer in (documents_writer, chunks_writer):
            if writer is not None:
                try:
                    writer.close()
                except BaseException:
                    pass
        for raw in (documents_raw, chunks_raw):
            if raw is not None:
                try:
                    raw.close()
                except BaseException:
                    pass
        for path in (documents_temporary, chunks_temporary):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _worker_initializer() -> None:
    """Keep Ctrl+C coordination in the parent so workers finish atomic shards."""

    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _report_progress(message: str) -> None:
    """Treat a detached console as a logging loss, never as corpus failure."""

    try:
        print(message, file=sys.stderr, flush=True)
    except OSError:
        pass


def _manifest_path(output: Path, part: WorkPart) -> Path:
    return output / "parts" / f"part-{part.ordinal:06d}.manifest.json"


def validate_part(output: Path, part: WorkPart, verify_hashes: bool = True) -> dict[str, object] | None:
    path = _manifest_path(output, part)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": SHARD_SCHEMA_VERSION,
        "part": part.ordinal,
        "first_block": part.first_block,
        "last_block": part.last_block,
        "block_count": len(part.blocks),
        "indexed_pages": sum(block.pages for block in part.blocks),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"Part {part.ordinal} manifest mismatch for {key}")
    files = value.get("files")
    if not isinstance(files, Mapping):
        raise ValueError(f"Part {part.ordinal} manifest has no files")
    for role in ("documents", "chunks"):
        entry = files.get(role)
        if not isinstance(entry, Mapping):
            raise ValueError(f"Part {part.ordinal} has no {role} file entry")
        shard = output / "parts" / str(entry.get("name"))
        if not shard.is_file() or shard.stat().st_size != entry.get("bytes"):
            raise ValueError(f"Part {part.ordinal} {role} shard is missing or has the wrong size")
        if verify_hashes and _sha256(shard) != entry.get("sha256"):
            raise ValueError(f"Part {part.ordinal} {role} shard checksum mismatch")
    return value


def aggregate_manifests(manifests: Sequence[Mapping[str, object]]) -> dict[str, int]:
    keys = ("block_count", "indexed_pages", "documents", "redirects", "chunks")
    totals = {key: sum(int(item[key]) for item in manifests) for key in keys}
    totals["compressed_bytes"] = sum(
        int(entry["bytes"])
        for item in manifests
        for entry in item["files"].values()  # type: ignore[union-attr]
    )
    return totals


def storage_projection(
    output: Path,
    totals: Mapping[str, int],
    selected_blocks: int,
    full_blocks: int,
    archive_bytes: int,
) -> dict[str, object]:
    ratio = full_blocks / max(1, int(totals["block_count"]))
    projected_shards = round(int(totals["compressed_bytes"]) * ratio)
    projected_chunks = round(int(totals["chunks"]) * ratio)
    projected_database = projected_chunks * DEFAULT_SQLITE_BYTES_PER_CHUNK
    disk = shutil.disk_usage(output)
    projected_total = archive_bytes + projected_shards + projected_database
    remaining_shards = max(0, projected_shards - int(totals["compressed_bytes"]))
    return {
        "sample_blocks": int(totals["block_count"]),
        "selected_blocks": selected_blocks,
        "full_archive_blocks": full_blocks,
        "projected_compressed_shards_bytes": projected_shards,
        "projected_chunks": projected_chunks,
        "sqlite_calibration_bytes_per_chunk": DEFAULT_SQLITE_BYTES_PER_CHUNK,
        "projected_sqlite_bytes": projected_database,
        "projected_archive_plus_shards_plus_sqlite_bytes": projected_total,
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "projected_free_after_build_bytes": disk.free - remaining_shards - projected_database,
    }


def _write_run_state(
    output: Path,
    plan: Mapping[str, object],
    manifests: Sequence[Mapping[str, object]],
    selected_parts: int,
    selected_blocks: int,
    stop_reason: str,
    started: float,
    error: BaseException | None = None,
) -> dict[str, object]:
    totals = aggregate_manifests(manifests) if manifests else {
        "block_count": 0,
        "indexed_pages": 0,
        "documents": 0,
        "redirects": 0,
        "chunks": 0,
        "compressed_bytes": 0,
    }
    full_blocks = int(plan["block_count"])
    completed = stop_reason == "archive_complete"
    state: dict[str, object] = {
        "schema_version": 1,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "completed": completed,
        "stop_reason": stop_reason,
        "parts": len(manifests),
        "selected_parts": selected_parts,
        "totals": totals,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "storage_projection": storage_projection(
            output,
            totals,
            selected_blocks,
            full_blocks,
            int(plan["archive_identity"]["bytes"]),  # type: ignore[index]
        ),
    }
    if error is not None:
        state["error"] = {"type": type(error).__name__, "message": str(error)}
    atomic_write_json(output / "extraction-stats.json", state)
    return state


def _write_corpus_manifest(
    output: Path,
    plan: Mapping[str, object],
    manifests: Sequence[Mapping[str, object]],
    completed: bool,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "corpus": "wikipedia-en",
        "completed": completed,
        "plan": "multistream-plan.json",
        "archive_identity": plan["archive_identity"],
        "configuration": plan["configuration"],
        "totals": aggregate_manifests(manifests),
        "parts": [
            {
                "part": item["part"],
                "manifest": f"parts/part-{int(item['part']):06d}.manifest.json",
                "documents": f"parts/{item['files']['documents']['name']}",  # type: ignore[index]
                "chunks": f"parts/{item['files']['chunks']['name']}",  # type: ignore[index]
            }
            for item in manifests
        ],
    }
    atomic_write_json(output / "corpus-manifest.json", value)
    return value


def extract_multistream(
    archive: Path,
    index: Path,
    output: Path,
    dump_date: str,
    workers: int = DEFAULT_WORKERS,
    batch_blocks: int = DEFAULT_BATCH_BLOCKS,
    target_part_mib: int = DEFAULT_TARGET_PART_MIB,
    max_chars: int = 3200,
    zstd_level: int = DEFAULT_ZSTD_LEVEL,
    max_parts: int | None = None,
    sample_parts: int | None = None,
    resume: bool = False,
    verify_existing: bool = True,
    stop_requested: threading.Event | None = None,
) -> dict[str, object]:
    if workers < 1 or batch_blocks < 1 or target_part_mib < 1 or max_chars < 1:
        raise ValueError("workers, batch_blocks, target_part_mib, and max_chars must be positive")
    if max_parts is not None and max_parts < 1:
        raise ValueError("max_parts must be positive")
    if sample_parts is not None and sample_parts < 1:
        raise ValueError("sample_parts must be positive")
    if max_parts is not None and sample_parts is not None:
        raise ValueError("max_parts and sample_parts are mutually exclusive")
    if not archive.is_file() or not index.is_file():
        raise FileNotFoundError("Archive and multistream index must both be regular files")
    stop_requested = stop_requested or threading.Event()
    plan_path = output / "multistream-plan.json"
    if output.exists() and any(output.iterdir()) and not resume:
        raise FileExistsError(f"Parallel extraction output already exists: {output}; use --resume")
    output.mkdir(parents=True, exist_ok=True)
    (output / "parts").mkdir(exist_ok=True)
    if resume:
        if not plan_path.is_file():
            raise FileNotFoundError("Resume requested but multistream-plan.json is missing")
        plan = load_plan(
            archive, index, plan_path, dump_date, max_chars, batch_blocks, target_part_mib
        )
    else:
        plan = build_plan(
            archive, index, plan_path, dump_date, max_chars, batch_blocks, target_part_mib
        )
    blocks = plan_blocks(plan)
    all_parts = work_parts(blocks, batch_blocks, target_part_mib * 1024 * 1024)
    if sample_parts is not None and sample_parts < len(all_parts):
        if sample_parts == 1:
            indexes = [len(all_parts) // 2]
        else:
            indexes = sorted(
                {round(item * (len(all_parts) - 1) / (sample_parts - 1)) for item in range(sample_parts)}
            )
        selected = [all_parts[index] for index in indexes]
    else:
        selected = all_parts[:max_parts] if max_parts is not None else all_parts
    selected_blocks = sum(len(part.blocks) for part in selected)
    manifests_by_part: dict[int, dict[str, object]] = {}
    for part in selected:
        existing = validate_part(output, part, verify_hashes=verify_existing)
        if existing is not None:
            manifests_by_part[part.ordinal] = existing
    pending = [part for part in selected if part.ordinal not in manifests_by_part]
    started = time.monotonic()
    _write_run_state(
        output,
        plan,
        [manifests_by_part[key] for key in sorted(manifests_by_part)],
        len(selected),
        selected_blocks,
        "in_progress",
        started,
    )
    try:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers, initializer=_worker_initializer
        ) as executor:
            active: dict[concurrent.futures.Future[dict[str, object]], WorkPart] = {}
            pending_iterator = iter(pending)

            def fill() -> None:
                while not stop_requested.is_set() and len(active) < workers * 2:
                    try:
                        part = next(pending_iterator)
                    except StopIteration:
                        return
                    future = executor.submit(
                        extract_part,
                        str(archive),
                        str(output),
                        part,
                        dump_date,
                        max_chars,
                        zstd_level,
                    )
                    active[future] = part

            fill()
            while active:
                done, _ = concurrent.futures.wait(active, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    part = active.pop(future)
                    manifest = future.result()
                    manifests_by_part[part.ordinal] = manifest
                    ordered = [manifests_by_part[key] for key in sorted(manifests_by_part)]
                    totals = aggregate_manifests(ordered)
                    rate = totals["documents"] / max(time.monotonic() - started, 0.001)
                    _report_progress(
                        f"parts={len(ordered)}/{len(selected)} blocks={totals['block_count']}/{selected_blocks} "
                        f"documents={totals['documents']} chunks={totals['chunks']} rate={rate:.1f} docs/s"
                    )
                    _write_run_state(
                        output,
                        plan,
                        ordered,
                        len(selected),
                        selected_blocks,
                        "in_progress",
                        started,
                    )
                fill()
            if stop_requested.is_set():
                raise ParallelExtractionInterrupted("Parallel extraction interrupted after durable shards")
    except ParallelExtractionInterrupted:
        ordered = [manifests_by_part[key] for key in sorted(manifests_by_part)]
        _write_corpus_manifest(output, plan, ordered, completed=False)
        _write_run_state(
            output, plan, ordered, len(selected), selected_blocks, "interrupted", started
        )
        raise
    except BaseException as error:
        ordered = [manifests_by_part[key] for key in sorted(manifests_by_part)]
        _write_corpus_manifest(output, plan, ordered, completed=False)
        _write_run_state(
            output, plan, ordered, len(selected), selected_blocks, "failed", started, error
        )
        raise
    ordered = [manifests_by_part[key] for key in sorted(manifests_by_part)]
    if len(selected) == len(all_parts):
        stop_reason = "archive_complete"
    elif sample_parts is not None:
        stop_reason = "sample_limit"
    else:
        stop_reason = "part_limit"
    _write_corpus_manifest(output, plan, ordered, completed=stop_reason == "archive_complete")
    return _write_run_state(
        output, plan, ordered, len(selected), selected_blocks, stop_reason, started
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parallel Wikimedia multistream extractor")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dump-date", required=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--batch-blocks", type=int, default=DEFAULT_BATCH_BLOCKS)
    parser.add_argument("--target-part-mib", type=int, default=DEFAULT_TARGET_PART_MIB)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--zstd-level", type=int, default=DEFAULT_ZSTD_LEVEL)
    parser.add_argument("--max-parts", type=int)
    parser.add_argument("--sample-parts", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--quick-resume", action="store_true", help="Check shard sizes without rehashing them")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    shutdown = threading.Event()
    previous_handler = signal.getsignal(signal.SIGINT)

    def request_shutdown(_signum: int, _frame: Any) -> None:
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    try:
        stats = extract_multistream(
            archive=args.archive,
            index=args.index,
            output=args.output,
            dump_date=args.dump_date,
            workers=args.workers,
            batch_blocks=args.batch_blocks,
            target_part_mib=args.target_part_mib,
            max_chars=args.max_chars,
            zstd_level=args.zstd_level,
            max_parts=args.max_parts,
            sample_parts=args.sample_parts,
            resume=args.resume,
            verify_existing=not args.quick_resume,
            stop_requested=shutdown,
        )
    except ParallelExtractionInterrupted as error:
        print(str(error), file=sys.stderr)
        return 130
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
