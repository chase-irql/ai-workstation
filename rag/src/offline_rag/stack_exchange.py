from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .documentation import ContentBlock, chunk_blocks, parse_html
from .records import CommonChunk, CommonDocument, make_content_id


MANIFEST_SCHEMA_VERSION = 1
ARTIFICIAL_POST_IDS = {1000000001, 1000000010}
TAG_RE = re.compile(r"<([^<>]+)>")
RECOGNIZED_OUTPUTS = {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json", "extraction-stats.json"}


def _integer(value: str | None, default: int = 0) -> int:
    return int(value) if value else default


def _tags(value: str | None) -> list[str]:
    return TAG_RE.findall(value or "")


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
    actual = {path.name for path in output.iterdir()}
    required = {"documents.jsonl", "chunks.jsonl", "corpus-manifest.json"}
    if not required.issubset(actual) or not actual.issubset(RECOGNIZED_OUTPUTS):
        raise ValueError(f"Refusing to replace unrecognized or mixed output directory: {output}")
    backup = output.with_name(f".{output.name}.replaced-{uuid.uuid4().hex}")
    os.replace(output, backup)
    try:
        os.replace(temporary, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def _iter_rows(path: Path) -> Iterator[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag.rsplit("}", 1)[-1] == "row":
            yield dict(element.attrib)
        element.clear()


def _create_stage(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL
        );
        CREATE TABLE questions (
            post_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            tags TEXT NOT NULL,
            accepted_answer_id INTEGER,
            score INTEGER NOT NULL,
            view_count INTEGER NOT NULL,
            answer_count INTEGER NOT NULL,
            creation_date TEXT NOT NULL,
            last_edit_date TEXT,
            last_activity_date TEXT,
            owner_user_id INTEGER,
            owner_display_name TEXT,
            content_license TEXT
        );
        CREATE TABLE answers (
            post_id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            score INTEGER NOT NULL,
            creation_date TEXT NOT NULL,
            last_edit_date TEXT,
            last_activity_date TEXT,
            owner_user_id INTEGER,
            owner_display_name TEXT,
            content_license TEXT
        );
        CREATE INDEX answers_parent_score ON answers(parent_id, score DESC, post_id);
        """
    )
    return connection


def _load_users(connection: sqlite3.Connection, path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    batch: list[tuple[int, str]] = []
    count = 0
    for row in _iter_rows(path):
        if not row.get("Id") or not row.get("DisplayName"):
            continue
        batch.append((int(row["Id"]), row["DisplayName"]))
        if len(batch) >= 5000:
            connection.executemany("INSERT OR REPLACE INTO users VALUES (?, ?)", batch)
            count += len(batch)
            batch.clear()
    if batch:
        connection.executemany("INSERT OR REPLACE INTO users VALUES (?, ?)", batch)
        count += len(batch)
    connection.commit()
    return count


def _load_posts(connection: sqlite3.Connection, path: Path) -> dict[str, int]:
    questions: list[tuple[Any, ...]] = []
    answers: list[tuple[Any, ...]] = []
    counts = {"questions_seen": 0, "answers_seen": 0, "other_post_types": 0, "artificial_rows_skipped": 0}

    def flush() -> None:
        if questions:
            connection.executemany("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", questions)
            questions.clear()
        if answers:
            connection.executemany("INSERT INTO answers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", answers)
            answers.clear()

    for row in _iter_rows(path):
        post_id = _integer(row.get("Id"), -1)
        if post_id in ARTIFICIAL_POST_IDS:
            counts["artificial_rows_skipped"] += 1
            continue
        post_type = _integer(row.get("PostTypeId"), -1)
        if post_type == 1:
            counts["questions_seen"] += 1
            questions.append(
                (
                    post_id,
                    row.get("Title") or f"Question {post_id}",
                    row.get("Body") or "",
                    json.dumps(_tags(row.get("Tags")), ensure_ascii=False, separators=(",", ":")),
                    _integer(row.get("AcceptedAnswerId"), 0) or None,
                    _integer(row.get("Score")),
                    _integer(row.get("ViewCount")),
                    _integer(row.get("AnswerCount")),
                    row.get("CreationDate") or "",
                    row.get("LastEditDate"),
                    row.get("LastActivityDate"),
                    _integer(row.get("OwnerUserId"), 0) or None,
                    row.get("OwnerDisplayName"),
                    row.get("ContentLicense"),
                )
            )
        elif post_type == 2 and row.get("ParentId"):
            counts["answers_seen"] += 1
            answers.append(
                (
                    post_id,
                    int(row["ParentId"]),
                    row.get("Body") or "",
                    _integer(row.get("Score")),
                    row.get("CreationDate") or "",
                    row.get("LastEditDate"),
                    row.get("LastActivityDate"),
                    _integer(row.get("OwnerUserId"), 0) or None,
                    row.get("OwnerDisplayName"),
                    row.get("ContentLicense"),
                )
            )
        else:
            counts["other_post_types"] += 1
        if len(questions) + len(answers) >= 5000:
            flush()
    flush()
    connection.commit()
    return counts


def _author(connection: sqlite3.Connection, owner_user_id: int | None, owner_display_name: str | None) -> str | None:
    if owner_display_name:
        return owner_display_name
    if owner_user_id is None:
        return None
    row = connection.execute("SELECT display_name FROM users WHERE user_id=?", (owner_user_id,)).fetchone()
    return str(row[0]) if row else None


def _document_id(corpus: str, post_id: int) -> str:
    return f"{corpus}:post:{post_id}"


def _instance_id(document_id: str, version: str, ordinal: int, heading: Sequence[str], text: str) -> str:
    identity = json.dumps([document_id, version, ordinal, list(heading), text], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _post_blocks(body: str, kind: str) -> list[ContentBlock]:
    parsed = parse_html(body, kind.title())
    prefix = "Question" if kind == "question" else "Answer"
    return [ContentBlock((prefix, *block.heading_path), block.text, block.kind, block.attributes) for block in parsed.blocks]


def _emit_post(
    documents_stream: Any,
    chunks_stream: Any,
    *,
    corpus: str,
    source_version: str,
    site_url: str,
    post_id: int,
    post_type: str,
    title: str,
    body: str,
    tags: list[str],
    score: int,
    creation_date: str,
    last_edit_date: str | None,
    last_activity_date: str | None,
    owner_user_id: int | None,
    owner_name: str | None,
    content_license: str | None,
    parent_question_id: int | None,
    accepted: bool,
    max_chars: int,
    min_chars: int,
    extra_attributes: dict[str, Any],
) -> int:
    values = chunk_blocks(_post_blocks(body, post_type), max_chars, min_chars)
    if not values:
        return 0
    document_id = _document_id(corpus, post_id)
    source_url = f"{site_url.rstrip('/')}/questions/{post_id}" if post_type == "question" else f"{site_url.rstrip('/')}/a/{post_id}"
    attributes = {
        "post_id": post_id,
        "post_type": post_type,
        "parent_question_id": parent_question_id,
        "accepted_answer": accepted,
        "score": score,
        "tags": tags,
        "owner_user_id": owner_user_id,
        "owner_display_name": owner_name,
        "creation_date": creation_date,
        "last_edit_date": last_edit_date,
        "last_activity_date": last_activity_date,
        "content_license": content_license,
        **extra_attributes,
    }
    document_text = "\n\n".join(value for _, value, _ in values)
    document = CommonDocument(
        document_id=document_id,
        corpus=corpus,
        title=title,
        source_url=source_url,
        source_version=source_version,
        source_timestamp=last_edit_date or creation_date,
        license=content_license,
        content_hash=make_content_id(document_text),
        attributes=attributes,
    )
    documents_stream.write(json.dumps(document.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
    instance_ids = [
        _instance_id(document_id, source_version, ordinal, heading, text)
        for ordinal, (heading, text, _) in enumerate(values)
    ]
    for ordinal, ((heading, text, block_attributes), instance_id) in enumerate(zip(values, instance_ids, strict=True)):
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
            attributes={**attributes, **block_attributes, "section_index": ordinal, "chunk_index": ordinal, "source_url": source_url},
        )
        chunks_stream.write(json.dumps(chunk.as_record(), ensure_ascii=False, sort_keys=True) + "\n")
    return len(values)


def import_stack_exchange(
    source_root: Path,
    output: Path,
    *,
    corpus: str,
    source_version: str,
    site_url: str,
    max_chars: int = 3200,
    min_chars: int = 300,
    force: bool = False,
) -> dict[str, object]:
    """Import a Stack Exchange site dump into common records atomically.

    Every retained post becomes a document so citations target the exact
    question or answer. Relationships and question tags remain in attributes.
    """

    posts_path = source_root / "Posts.xml"
    users_path = source_root / "Users.xml"
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if not posts_path.is_file():
        raise FileNotFoundError(posts_path)
    if not corpus or not source_version or not site_url.startswith("https://"):
        raise ValueError("corpus, source_version, and an HTTPS site_url are required")
    if max_chars < 128 or min_chars < 0 or min_chars > max_chars:
        raise ValueError("max_chars must be at least 128 and min_chars must be between zero and max_chars")
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; use --force to replace recognized importer output")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    stage_path = temporary / "stack-exchange-stage.sqlite3"
    started = datetime.now(timezone.utc)
    connection: sqlite3.Connection | None = None
    try:
        connection = _create_stage(stage_path)
        users = _load_users(connection, users_path if users_path.is_file() else None)
        scanned = _load_posts(connection, posts_path)
        documents_path = temporary / "documents.jsonl"
        chunks_path = temporary / "chunks.jsonl"
        documents = 0
        chunks = 0
        question_documents = 0
        accepted_answers = 0
        positive_answers = 0
        skipped_empty = 0
        licenses: dict[str, int] = {}
        with documents_path.open("w", encoding="utf-8", newline="\n") as documents_stream, chunks_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as chunks_stream:
            questions = connection.execute(
                """SELECT post_id, title, body, tags, accepted_answer_id, score, view_count, answer_count,
                          creation_date, last_edit_date, last_activity_date, owner_user_id,
                          owner_display_name, content_license
                   FROM questions ORDER BY post_id"""
            )
            for question in questions:
                (
                    question_id, title, body, tags_json, accepted_id, score, view_count, answer_count,
                    creation_date, last_edit_date, last_activity_date, owner_user_id, owner_display_name,
                    content_license,
                ) = question
                tag_values = json.loads(tags_json)
                author = _author(connection, owner_user_id, owner_display_name)
                count = _emit_post(
                    documents_stream, chunks_stream, corpus=corpus, source_version=source_version,
                    site_url=site_url, post_id=question_id, post_type="question", title=title, body=body,
                    tags=tag_values, score=score, creation_date=creation_date, last_edit_date=last_edit_date,
                    last_activity_date=last_activity_date, owner_user_id=owner_user_id, owner_name=author,
                    content_license=content_license, parent_question_id=None, accepted=False,
                    max_chars=max_chars, min_chars=min_chars,
                    extra_attributes={"accepted_answer_id": accepted_id, "view_count": view_count, "answer_count": answer_count},
                )
                if count:
                    documents += 1
                    question_documents += 1
                    chunks += count
                    licenses[content_license or "unknown"] = licenses.get(content_license or "unknown", 0) + 1
                else:
                    skipped_empty += 1
                answers = connection.execute(
                    """SELECT post_id, body, score, creation_date, last_edit_date, last_activity_date,
                              owner_user_id, owner_display_name, content_license
                       FROM answers WHERE parent_id=? AND (post_id=? OR score>0)
                       ORDER BY (post_id=?) DESC, score DESC, post_id""",
                    (question_id, accepted_id or -1, accepted_id or -1),
                ).fetchall()
                for answer in answers:
                    answer_id, answer_body, answer_score, answer_created, answer_edited, answer_activity, answer_owner_id, answer_owner_display, answer_license = answer
                    is_accepted = answer_id == accepted_id
                    answer_author = _author(connection, answer_owner_id, answer_owner_display)
                    count = _emit_post(
                        documents_stream, chunks_stream, corpus=corpus, source_version=source_version,
                        site_url=site_url, post_id=answer_id, post_type="answer", title=title, body=answer_body,
                        tags=tag_values, score=answer_score, creation_date=answer_created, last_edit_date=answer_edited,
                        last_activity_date=answer_activity, owner_user_id=answer_owner_id, owner_name=answer_author,
                        content_license=answer_license, parent_question_id=question_id, accepted=is_accepted,
                        max_chars=max_chars, min_chars=min_chars, extra_attributes={"question_title": title},
                    )
                    if count:
                        documents += 1
                        chunks += count
                        accepted_answers += int(is_accepted)
                        positive_answers += int(not is_accepted)
                        licenses[answer_license or "unknown"] = licenses.get(answer_license or "unknown", 0) + 1
                    else:
                        skipped_empty += 1
            for stream in (documents_stream, chunks_stream):
                stream.flush()
                os.fsync(stream.fileno())
        if documents == 0 or chunks == 0:
            raise ValueError("Stack Exchange import produced no searchable records")
        retained_answer_rows = accepted_answers + positive_answers
        skipped_answers = scanned["answers_seen"] - retained_answer_rows
        connection.close()
        connection = None
        stage_path.unlink()
        files = {
            "documents": {"path": "documents.jsonl", "bytes": documents_path.stat().st_size, "sha256": _sha256(documents_path)},
            "chunks": {"path": "chunks.jsonl", "bytes": chunks_path.stat().st_size, "sha256": _sha256(chunks_path)},
        }
        finished = datetime.now(timezone.utc)
        stats = {
            "schema_version": 1,
            "output_schema_version": 1,
            "completed": True,
            "stop_reason": "source_complete",
            "users": users,
            **scanned,
            "question_documents": question_documents,
            "accepted_answers": accepted_answers,
            "other_positive_answers": positive_answers,
            "answers_excluded_by_policy": skipped_answers,
            "documents": documents,
            "chunks": chunks,
            "skipped_empty": skipped_empty,
            "licenses": licenses,
            "source_bytes": posts_path.stat().st_size + (users_path.stat().st_size if users_path.is_file() else 0),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        }
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "record_format": "offline-rag-common-jsonl-v1",
            "record_schema_version": 1,
            "corpus": corpus,
            "source_version": source_version,
            "source_timestamp": None,
            "license": "per-post ContentLicense",
            "base_url": site_url,
            "completed": True,
            "stop_reason": "source_complete",
            "counts": {"documents": documents, "chunks": chunks},
            "configuration": {
                "max_chars": max_chars,
                "min_chars": min_chars,
                "retention_policy": "all questions; accepted answers regardless of score; other answers with score > 0",
                "document_granularity": "one document per retained post",
            },
            "source_files": {
                "Posts.xml": {"bytes": posts_path.stat().st_size, "sha256": _sha256(posts_path)},
                **({"Users.xml": {"bytes": users_path.stat().st_size, "sha256": _sha256(users_path)}} if users_path.is_file() else {}),
            },
            "parts": [{
                "part": 0,
                "documents": "documents.jsonl",
                "chunks": "chunks.jsonl",
                "documents_sha256": files["documents"]["sha256"],
                "chunks_sha256": files["chunks"]["sha256"],
            }],
            "files": files,
        }
        _atomic_json(temporary / "extraction-stats.json", stats)
        _atomic_json(temporary / "corpus-manifest.json", manifest)
        _publish_directory(temporary, output, force)
        return {"output": str(output.resolve()), "documents": documents, "chunks": chunks, **stats}
    except BaseException:
        if connection is not None:
            connection.close()
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a Stack Exchange XML site dump into common RAG records.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(import_stack_exchange(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
