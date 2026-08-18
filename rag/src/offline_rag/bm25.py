from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import zstandard

from .records import CommonChunk, wikipedia_chunks_to_common, wikipedia_document_to_common


INDEX_SCHEMA_VERSION = 2
TOKENIZER_CONFIGURATION = "unicode61 remove_diacritics 2"
QUERY_MODES = ("and", "or", "phrase", "exact")
QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "are",
        "be",
        "been",
        "being",
        "did",
        "do",
        "does",
        "how",
        "is",
        "me",
        "of",
        "tell",
        "the",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)
TECHNICAL_PATTERNS = (
    (re.compile(r"(?i)(?<![\w+])c\+\+(?!\+)") , "cpp"),
    (re.compile(r"(?i)(?<![\w#])c#(?!#)"), "csharp"),
    (re.compile(r"(?i)(?<!\w)\.net(?!\w)"), "dotnet"),
)
SCOPED_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*(?:::[A-Za-z_]\w*)+\b", re.UNICODE)
UNDERSCORE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z]\w*(?:_\w+)+\b", re.UNICODE)
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


SCHEMA = f"""
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    corpus TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    source_version TEXT,
    source_timestamp TEXT,
    license TEXT,
    content_hash TEXT,
    attributes_json TEXT NOT NULL
);
CREATE TABLE chunks (
    row_id INTEGER PRIMARY KEY,
    chunk_instance_id TEXT NOT NULL UNIQUE,
    content_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    parent_chunk_id TEXT,
    ordinal INTEGER NOT NULL,
    heading_path TEXT NOT NULL,
    text TEXT NOT NULL,
    character_count INTEGER NOT NULL,
    token_count INTEGER,
    previous_chunk_id TEXT,
    next_chunk_id TEXT,
    attributes_json TEXT NOT NULL
);
CREATE INDEX chunks_document_id_idx ON chunks(document_id);
CREATE INDEX chunks_content_id_idx ON chunks(content_id);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    title,
    heading_path,
    text,
    technical_normalized,
    content='',
    tokenize='{TOKENIZER_CONFIGURATION}'
);
CREATE TABLE index_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    mode: str
    normalized_terms: tuple[str, ...]
    fts_expression: str
    used_technical_normalization: bool


@dataclass(frozen=True)
class CorpusInputs:
    documents: tuple[Path, ...]
    chunks: tuple[Path, ...]
    corpus_manifest: dict[str, Any] | None = None


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    opener = zstandard.open if path.suffix.casefold() == ".zst" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object in {path} at line {line_number}")
            yield value


def _identifier_alias(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}"


def technical_normalized_text(value: str) -> str:
    """Return tokenizer-safe text only when a recognized technical term occurs.

    C++, C#, and .NET receive readable aliases. Scoped and underscore identifiers
    receive stable hash aliases, avoiding false claims that unicode61 preserves
    their punctuation exactly.
    """

    normalized = value
    changed = False
    for pattern, replacement in TECHNICAL_PATTERNS:
        normalized, count = pattern.subn(f" {replacement} ", normalized)
        changed = changed or count > 0

    def replace_scoped(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f" {_identifier_alias('scope', match.group(0))} "

    def replace_underscore(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f" {_identifier_alias('ident', match.group(0))} "

    normalized = SCOPED_IDENTIFIER_RE.sub(replace_scoped, normalized)
    normalized = UNDERSCORE_IDENTIFIER_RE.sub(replace_underscore, normalized)
    if not changed:
        return ""
    return " ".join(token.casefold() for token in WORD_RE.findall(normalized))


def query_terms(value: str) -> tuple[tuple[str, ...], bool]:
    technical = technical_normalized_text(value)
    if technical:
        return tuple(technical.split()), True
    return tuple(token.casefold() for token in WORD_RE.findall(value)), False


def plan_query(value: str, mode: str = "and") -> QueryPlan:
    if mode not in QUERY_MODES:
        raise ValueError(f"Unsupported query mode {mode!r}; choose from {', '.join(QUERY_MODES)}")
    terms, used_technical = query_terms(value)
    if not terms:
        raise ValueError("Query contains no searchable terms")
    # Question scaffolding is harmful when every token is required by an AND
    # query (for example, `what is albedo` would otherwise require `what` in
    # the matching chunk). Phrase/exact modes intentionally retain every token.
    if mode in {"and", "or"}:
        meaningful_terms = tuple(term for term in terms if term not in QUERY_STOP_WORDS)
        if meaningful_terms:
            terms = meaningful_terms
    escaped = [term.replace('"', '""') for term in terms]
    effective_mode = "phrase" if mode == "exact" else mode
    if effective_mode == "phrase":
        expression = '"' + " ".join(escaped) + '"'
    else:
        operator = " AND " if effective_mode == "and" else " OR "
        expression = operator.join(f'"{term}"' for term in escaped)
    return QueryPlan(
        original_query=value,
        mode=mode,
        normalized_terms=terms,
        fts_expression=expression,
        used_technical_normalization=used_technical,
    )


def fts_query(value: str, mode: str = "and") -> str:
    """Compatibility wrapper returning the deterministic FTS5 expression."""

    return plan_query(value, mode).fts_expression


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _batched(values: Iterable[tuple[Any, ...]], size: int = 1000) -> Iterator[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _document_rows(paths: Sequence[Path]) -> Iterator[tuple[Any, ...]]:
    for path in paths:
        for item in read_jsonl(path):
            document = wikipedia_document_to_common(item)
            yield (
                document.document_id,
                document.corpus,
                document.title,
                document.source_url,
                document.source_version,
                document.source_timestamp,
                document.license,
                document.content_hash,
                _json(document.attributes),
            )


def _chunk_rows(paths: Sequence[Path]) -> Iterator[tuple[Any, ...]]:
    for path in paths:
        common_chunks: Iterable[CommonChunk] = wikipedia_chunks_to_common(read_jsonl(path))
        for chunk in common_chunks:
            yield (
                chunk.chunk_instance_id,
                chunk.content_id,
                chunk.document_id,
                chunk.parent_chunk_id,
                chunk.ordinal,
                " > ".join(chunk.heading_path),
                chunk.text,
                chunk.character_count,
                chunk.token_count,
                chunk.previous_chunk_id,
                chunk.next_chunk_id,
                _json(chunk.attributes),
            )


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path}")
    return value


def _safe_manifest_path(input_directory: Path, relative: object) -> Path:
    root = input_directory.resolve()
    path = (root / str(relative)).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Corpus manifest path escapes its input directory: {relative!r}")
    return path


def _corpus_inputs(input_directory: Path) -> CorpusInputs:
    documents = input_directory / "documents.jsonl"
    chunks = input_directory / "chunks.jsonl"
    if documents.is_file() and chunks.is_file():
        return CorpusInputs(documents=(documents,), chunks=(chunks,))
    manifest_path = input_directory / "corpus-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            "Input directory must contain legacy documents/chunks JSONL or corpus-manifest.json"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Corpus manifest must contain a JSON object")
    raw_parts = manifest.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("Corpus manifest contains no parts")
    ordered = sorted(raw_parts, key=lambda item: int(item["part"]))
    part_numbers = [int(item["part"]) for item in ordered]
    if len(part_numbers) != len(set(part_numbers)):
        raise ValueError("Corpus manifest part numbers must be unique")
    document_paths = tuple(_safe_manifest_path(input_directory, item["documents"]) for item in ordered)
    chunk_paths = tuple(_safe_manifest_path(input_directory, item["chunks"]) for item in ordered)
    for path in (*document_paths, *chunk_paths):
        if not path.is_file():
            raise FileNotFoundError(f"Corpus shard is missing: {path}")
    return CorpusInputs(documents=document_paths, chunks=chunk_paths, corpus_manifest=manifest)


def _input_sizes(inputs: CorpusInputs) -> tuple[int, ...]:
    return tuple(path.stat().st_size for path in (*inputs.documents, *inputs.chunks))


def _input_context(input_directory: Path, inputs: CorpusInputs) -> dict[str, Any]:
    context: dict[str, Any] = {
        "input_directory": str(input_directory.resolve()),
        "documents_bytes": sum(path.stat().st_size for path in inputs.documents),
        "chunks_bytes": sum(path.stat().st_size for path in inputs.chunks),
        "document_files": len(inputs.documents),
        "chunk_files": len(inputs.chunks),
    }
    for name in ("checkpoint.json", "extraction-stats.json", "corpus-manifest.json"):
        path = input_directory / name
        if path.is_file():
            content = path.read_bytes()
            context[name] = json.loads(content)
            context[f"{name}_sha256"] = hashlib.sha256(content).hexdigest()
    archive_value = (context.get("extraction-stats.json") or {}).get("archive")
    if not archive_value:
        corpus_manifest = context.get("corpus-manifest.json") or {}
        archive_value = (corpus_manifest.get("archive_identity") or {}).get("path")
    if archive_value:
        manifest_path = Path(str(archive_value)).parent / "manifest.json"
        if manifest_path.is_file():
            content = manifest_path.read_bytes()
            context["source_manifest"] = json.loads(content)
            context["source_manifest_sha256"] = hashlib.sha256(content).hexdigest()
    fingerprint_value = {key: value for key, value in context.items() if key != "input_directory"}
    context["input_fingerprint"] = hashlib.sha256(_json(fingerprint_value).encode("utf-8")).hexdigest()
    return context


def _validate_input_state(context: Mapping[str, Any], allow_incomplete: bool) -> None:
    state = context.get("extraction-stats.json") or context.get("checkpoint.json")
    if not isinstance(state, Mapping):
        return
    stop_reason = state.get("stop_reason")
    if stop_reason is None and "checkpoint.json" in context and not bool(state.get("completed")):
        stop_reason = "legacy_incomplete"
    if not bool(state.get("completed")) and not allow_incomplete:
        raise ValueError(f"Refusing to index extraction with stop_reason={stop_reason!r}; use allow_incomplete")


def _set_metadata(connection: sqlite3.Connection, values: Mapping[str, object]) -> None:
    connection.executemany(
        "INSERT INTO index_metadata(key, value_json) VALUES (?, ?)",
        ((key, _json(value)) for key, value in sorted(values.items())),
    )


def _validate_index(
    connection: sqlite3.Connection,
    expected_documents: int,
    expected_chunks: int,
    smoke_query: str,
) -> None:
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if foreign_keys != 1:
        raise RuntimeError("SQLite foreign-key enforcement is not enabled")
    actual_documents = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
    actual_chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
    fts_rows = connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    if actual_documents != expected_documents:
        raise RuntimeError(f"Document count mismatch: expected {expected_documents}, found {actual_documents}")
    if actual_chunks != expected_chunks:
        raise RuntimeError(f"Chunk count mismatch: expected {expected_chunks}, found {actual_chunks}")
    if fts_rows != expected_chunks:
        raise RuntimeError(f"FTS row count mismatch: expected {expected_chunks}, found {fts_rows}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Foreign-key violations detected: {violations[:5]}")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    match = connection.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 1",
        (smoke_query,),
    ).fetchone()
    if match is None:
        raise RuntimeError("FTS smoke-test query returned no rows")


def _temporary_database_path(database: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{database.name}.", suffix=".building", dir=database.parent)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _cleanup_builder_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _cleanup_builder_sidecars(path: Path) -> None:
    for candidate in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def build_index(
    input_directory: Path,
    database: Path,
    overwrite: bool = False,
    allow_incomplete: bool = False,
) -> dict[str, object]:
    """Build and validate beside the destination, then atomically publish it."""

    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists() and not overwrite:
        raise FileExistsError(f"Database already exists: {database}; authorize overwrite explicitly")
    existing_sidecars = [path for path in (Path(f"{database}-wal"), Path(f"{database}-shm")) if path.exists()]
    if existing_sidecars:
        names = ", ".join(path.name for path in existing_sidecars)
        raise RuntimeError(f"Refusing replacement while destination SQLite sidecars exist: {names}")
    inputs = _corpus_inputs(input_directory)
    initial_sizes = _input_sizes(inputs)
    context = _input_context(input_directory, inputs)
    _validate_input_state(context, allow_incomplete)
    temporary = _temporary_database_path(database)
    connection: sqlite3.Connection | None = None
    started = time.monotonic()
    document_count = 0
    chunk_count = 0
    smoke_expression: str | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(SCHEMA)
        document_sql = "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        for batch in _batched(_document_rows(inputs.documents)):
            connection.executemany(document_sql, batch)
            document_count += len(batch)
        connection.commit()
        chunk_sql = (
            "INSERT INTO chunks(chunk_instance_id, content_id, document_id, parent_chunk_id, ordinal, "
            "heading_path, text, character_count, token_count, previous_chunk_id, next_chunk_id, attributes_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        for batch in _batched(_chunk_rows(inputs.chunks)):
            connection.executemany(chunk_sql, batch)
            chunk_count += len(batch)
            if smoke_expression is None:
                candidate_text = f"{batch[0][5]} {batch[0][6]}"
                terms, _ = query_terms(candidate_text)
                if terms:
                    smoke_expression = f'"{terms[0]}"'
            if chunk_count % 10_000 == 0:
                connection.commit()
        connection.commit()
        if chunk_count == 0 or smoke_expression is None:
            raise ValueError("Cannot build a searchable index with no searchable chunks")
        connection.create_function("technical_normalized", 1, technical_normalized_text, deterministic=True)
        for first_row in range(1, chunk_count + 1, 10_000):
            last_row = min(chunk_count, first_row + 9_999)
            connection.execute(
                """
                INSERT INTO chunks_fts(rowid, title, heading_path, text, technical_normalized)
                SELECT c.row_id, d.title, c.heading_path, c.text,
                       technical_normalized(d.title || ' ' || c.heading_path || ' ' || c.text)
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                WHERE c.row_id BETWEEN ? AND ?
                ORDER BY c.row_id
                """,
                (first_row, last_row),
            )
            connection.commit()
        final_sizes = _input_sizes(inputs)
        if final_sizes != initial_sizes:
            raise RuntimeError("Input JSONL files changed during index construction")
        stats_state = context.get("extraction-stats.json")
        if isinstance(stats_state, Mapping):
            count_state = stats_state.get("totals", stats_state)
            if not isinstance(count_state, Mapping):
                raise RuntimeError("Extraction statistics totals are invalid")
            if "documents" in count_state and int(count_state["documents"]) != document_count:
                raise RuntimeError("Document count does not match extraction statistics")
            if "chunks" in count_state and int(count_state["chunks"]) != chunk_count:
                raise RuntimeError("Chunk count does not match extraction statistics")
        corpora = [row[0] for row in connection.execute("SELECT DISTINCT corpus FROM documents ORDER BY corpus")]
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT source_version FROM documents WHERE source_version IS NOT NULL ORDER BY source_version"
            )
        ]
        metadata = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source_corpora": corpora,
            "source_versions": versions,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "input_context": context,
            "tokenizer": TOKENIZER_CONFIGURATION,
            "query_configuration": {
                "default_mode": "and",
                "modes": list(QUERY_MODES),
                "technical_aliases": ["C++=cpp", "C#=csharp", ".NET=dotnet"],
                "identifier_aliases": "sha256-derived tokenizer-safe aliases for :: and _ identifiers",
                "question_stop_words": sorted(QUERY_STOP_WORDS),
                "exact_title_promotion": True,
            },
        }
        metadata["build_id"] = hashlib.sha256(
            _json(
                {
                    "schema_version": INDEX_SCHEMA_VERSION,
                    "input_fingerprint": context["input_fingerprint"],
                    "tokenizer": TOKENIZER_CONFIGURATION,
                    "query_configuration": metadata["query_configuration"],
                }
            ).encode("utf-8")
        ).hexdigest()
        _set_metadata(connection, metadata)
        connection.commit()
        _validate_index(connection, document_count, chunk_count, smoke_expression)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if str(journal_mode).casefold() != "delete":
            raise RuntimeError(f"Failed to finalize SQLite journal mode: {journal_mode}")
        connection.close()
        connection = None
        _cleanup_builder_sidecars(temporary)
        if database.exists() and not overwrite:
            raise FileExistsError(f"Database appeared during build: {database}")
        os.replace(temporary, database)
    except BaseException:
        if connection is not None:
            connection.close()
        _cleanup_builder_files(temporary)
        raise
    return {
        "database": str(database.resolve()),
        "schema_version": INDEX_SCHEMA_VERSION,
        "documents": document_count,
        "chunks": chunk_count,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (name,),
    ).fetchone() is not None


def read_index_metadata(database: Path) -> dict[str, Any]:
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        if not _table_exists(connection, "index_metadata"):
            return {"schema_version": 1}
        return {
            key: json.loads(value)
            for key, value in connection.execute("SELECT key, value_json FROM index_metadata ORDER BY key")
        }
    finally:
        connection.close()


def _citation(corpus: str, title: str, heading_path: list[str], timestamp: str | None, url: str | None) -> str:
    label = "Wikipedia" if corpus == "wikipedia-en" else corpus
    section = f" § {' > '.join(heading_path)}" if heading_path else ""
    revision = f" ({timestamp})" if timestamp else ""
    source = f" {url}" if url else ""
    return f"{label} — {title}{section}{revision}{source}"


def _search_v2(
    connection: sqlite3.Connection,
    plan: QueryPlan,
    limit: int,
) -> list[dict[str, object]]:
    select_sql = """
        SELECT c.chunk_instance_id AS chunk_id, c.document_id, d.corpus, d.title,
               c.heading_path, c.text, d.source_url, d.source_timestamp,
               c.ordinal, c.attributes_json,
               bm25(chunks_fts, 5.0, 2.0, 1.0, 2.0) AS raw_score
        FROM chunks_fts
        JOIN chunks c ON c.row_id = chunks_fts.rowid
        JOIN documents d ON d.document_id = c.document_id
    """
    promoted_rows: list[sqlite3.Row] = []
    # BM25 length normalization naturally favors short, specialized pages over
    # a long canonical article even when the query exactly names that article.
    # Search engines conventionally promote an exact title hit. The FTS title
    # constraint makes this lookup indexed; the documents predicate prevents a
    # similarly named page from being silently treated as exact.
    if plan.mode in {"and", "or"}:
        requested_title = " ".join(plan.normalized_terms)
        escaped_title = requested_title.replace('"', '""')
        title_expression = f'title : "{escaped_title}"'
        promoted_rows = connection.execute(
            select_sql
            + """
            WHERE chunks_fts MATCH ? AND d.title = ? COLLATE NOCASE
            ORDER BY c.ordinal, c.row_id
            LIMIT 1
            """,
            (title_expression, requested_title),
        ).fetchall()
    promoted_documents = {str(row["document_id"]) for row in promoted_rows}
    rows = connection.execute(
        select_sql
        + """
        WHERE chunks_fts MATCH ?
        ORDER BY raw_score, c.row_id
        LIMIT ?
        """,
        (plan.fts_expression, limit + len(promoted_rows)),
    ).fetchall()
    ordered_rows = promoted_rows + [row for row in rows if str(row["document_id"]) not in promoted_documents]
    results: list[dict[str, object]] = []
    for row in ordered_rows[:limit]:
        item = dict(row)
        attributes = json.loads(item.pop("attributes_json"))
        heading_path = [part.strip() for part in item["heading_path"].split(">") if part.strip()]
        item["heading_path"] = heading_path
        item["revision_timestamp"] = attributes.get("revision_timestamp") or item.pop("source_timestamp")
        item["section_index"] = attributes.get("section_index")
        item["chunk_index"] = attributes.get("chunk_index")
        item["score"] = item["raw_score"]
        item["query"] = plan.original_query
        item["query_mode"] = plan.mode
        item["normalized_terms"] = list(plan.normalized_terms)
        item["ranking_reason"] = "exact_title" if str(item["document_id"]) in promoted_documents else "bm25"
        item["citation"] = _citation(
            str(item["corpus"]),
            str(item["title"]),
            heading_path,
            item["revision_timestamp"],
            item["source_url"],
        )
        results.append(item)
    return results


def _search_v1(
    connection: sqlite3.Connection,
    plan: QueryPlan,
    limit: int,
) -> list[dict[str, object]]:
    # Version-1 indexes have no technical alias column. Normal terms remain usable,
    # while punctuation-exact technical matching requires rebuilding as version 2.
    legacy_terms = tuple(token.casefold() for token in WORD_RE.findall(plan.original_query))
    if not legacy_terms:
        raise ValueError("Query contains no terms supported by the version-1 index")
    operator = " OR " if plan.mode == "or" else " AND "
    if plan.mode in {"phrase", "exact"}:
        expression = '"' + " ".join(legacy_terms) + '"'
    else:
        expression = operator.join(f'"{term}"' for term in legacy_terms)
    rows = connection.execute(
        """
        SELECT c.chunk_id, c.document_id, 'wikipedia-en' AS corpus, d.title,
               c.heading_path, c.text, d.source_url, d.revision_timestamp,
               c.section_index, c.chunk_index,
               bm25(chunks_fts, 5.0, 2.0, 1.0) AS raw_score
        FROM chunks_fts
        JOIN chunks c ON c.row_id = chunks_fts.rowid
        JOIN documents d ON d.document_id = c.document_id
        WHERE chunks_fts MATCH ?
        ORDER BY raw_score, c.row_id
        LIMIT ?
        """,
        (expression, limit),
    ).fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        heading_path = [part.strip() for part in item["heading_path"].split(">") if part.strip()]
        item["heading_path"] = heading_path
        item["score"] = item["raw_score"]
        item["query"] = plan.original_query
        item["query_mode"] = plan.mode
        item["normalized_terms"] = list(plan.normalized_terms)
        item["citation"] = _citation(
            "wikipedia-en",
            str(item["title"]),
            heading_path,
            item["revision_timestamp"],
            item["source_url"],
        )
        results.append(item)
    return results


def search(database: Path, query: str, limit: int = 8, mode: str = "and") -> list[dict[str, object]]:
    if not database.is_file():
        raise FileNotFoundError(database)
    if limit < 1:
        raise ValueError("limit must be positive")
    plan = plan_query(query, mode)
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if _table_exists(connection, "index_metadata"):
            return _search_v2(connection, plan, limit)
        return _search_v1(connection, plan, limit)
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or query the CPU-only corpus BM25 index.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--input", type=Path, required=True)
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--overwrite", action="store_true")
    build.add_argument("--allow-incomplete", action="store_true")
    query = subparsers.add_parser("query")
    query.add_argument("--database", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--mode", choices=QUERY_MODES, default="and")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        result = build_index(args.input, args.database, args.overwrite, args.allow_incomplete)
    else:
        result = search(args.database, args.query, args.limit, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
