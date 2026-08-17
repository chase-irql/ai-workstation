from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    dump_date TEXT NOT NULL,
    article_id INTEGER NOT NULL,
    revision_id INTEGER,
    revision_timestamp TEXT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    redirect_target TEXT
);
CREATE TABLE chunks (
    row_id INTEGER PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    section_index INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    heading_path TEXT NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    title,
    heading_path,
    text,
    content='chunks_search',
    content_rowid='row_id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE chunks_search (
    row_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX chunks_document_id_idx ON chunks(document_id);
"""


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def build_index(input_directory: Path, database: Path) -> dict[str, object]:
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    connection = sqlite3.connect(database)
    started = time.monotonic()
    try:
        connection.executescript(SCHEMA)
        documents = 0
        for item in read_jsonl(input_directory / "documents.jsonl"):
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["document_id"], item["source"], item["dump_date"], item["article_id"],
                    item["revision_id"], item["revision_timestamp"], item["title"], item["source_url"],
                    item["redirect_target"],
                ),
            )
            documents += 1
        titles = dict(connection.execute("SELECT document_id, title FROM documents"))
        chunks = 0
        for item in read_jsonl(input_directory / "chunks.jsonl"):
            heading = " > ".join(item["heading_path"])
            cursor = connection.execute(
                "INSERT INTO chunks(chunk_id, document_id, section_index, chunk_index, heading_path, text, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item["chunk_id"], item["document_id"], item["section_index"], item["chunk_index"],
                    heading, item["text"], item["content_hash"],
                ),
            )
            row_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO chunks_search(row_id, title, heading_path, text) VALUES (?, ?, ?, ?)",
                (row_id, titles[item["document_id"]], heading, item["text"]),
            )
            chunks += 1
            if chunks % 1000 == 0:
                connection.commit()
        connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
        connection.commit()
    finally:
        connection.close()
    return {
        "database": str(database.resolve()),
        "documents": documents,
        "chunks": chunks,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def fts_query(value: str) -> str:
    tokens = re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", value, flags=re.UNICODE)
    if not tokens:
        raise ValueError("Query contains no searchable terms")
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def search(database: Path, query: str, limit: int = 8) -> list[dict[str, object]]:
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT c.chunk_id, c.document_id, d.title, c.heading_path, c.text,
                   d.source_url, d.revision_timestamp,
                   bm25(chunks_fts, 5.0, 2.0, 1.0) AS score
            FROM chunks_fts
            JOIN chunks c ON c.row_id = chunks_fts.rowid
            JOIN documents d ON d.document_id = c.document_id
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query(query), limit),
        ).fetchall()
    finally:
        connection.close()
    results = []
    for row in rows:
        item = dict(row)
        section = f" § {item['heading_path']}" if item["heading_path"] else ""
        item["citation"] = f"Wikipedia — {item['title']}{section} ({item['revision_timestamp']}) {item['source_url']}"
        results.append(item)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or query the CPU-only Wikipedia BM25 index.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--input", type=Path, required=True)
    build.add_argument("--database", type=Path, required=True)
    query = subparsers.add_parser("query")
    query.add_argument("--database", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=8)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        result = build_index(args.input, args.database)
    else:
        result = search(args.database, args.query, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
