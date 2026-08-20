from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from itertools import chain
from typing import Any


COMMON_RECORD_SCHEMA_VERSION = 1


def normalize_content(text: str) -> str:
    """Return the stable normalization used for content-addressed identifiers."""

    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+\n", "\n", normalized).strip()


def make_content_id(text: str) -> str:
    digest = hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _required_string(item: Mapping[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Common record field {name!r} must be a nonempty string")
    return value


def _optional_string(item: Mapping[str, Any], name: str) -> str | None:
    value = item.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Common record field {name!r} must be a string or null")
    return value


def _attributes(item: Mapping[str, Any]) -> dict[str, Any]:
    value = item.get("attributes", {})
    if not isinstance(value, Mapping):
        raise ValueError("Common record field 'attributes' must be an object")
    return dict(value)


@dataclass(frozen=True)
class CommonDocument:
    document_id: str
    corpus: str
    title: str
    source_url: str | None = None
    source_version: str | None = None
    source_timestamp: str | None = None
    license: str | None = None
    content_hash: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    schema_version: int = COMMON_RECORD_SCHEMA_VERSION

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CommonChunk:
    chunk_instance_id: str
    content_id: str
    document_id: str
    parent_chunk_id: str | None
    ordinal: int
    heading_path: list[str]
    text: str
    character_count: int
    token_count: int | None
    previous_chunk_id: str | None
    next_chunk_id: str | None
    attributes: dict[str, Any] = field(default_factory=dict)
    schema_version: int = COMMON_RECORD_SCHEMA_VERSION

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def common_document_from_record(item: Mapping[str, Any]) -> CommonDocument:
    """Validate and deserialize a native common document record."""

    schema_version = int(item.get("schema_version", COMMON_RECORD_SCHEMA_VERSION))
    if schema_version != COMMON_RECORD_SCHEMA_VERSION:
        raise ValueError(f"Unsupported common document schema version: {schema_version}")
    return CommonDocument(
        document_id=_required_string(item, "document_id"),
        corpus=_required_string(item, "corpus"),
        title=_required_string(item, "title"),
        source_url=_optional_string(item, "source_url"),
        source_version=_optional_string(item, "source_version"),
        source_timestamp=_optional_string(item, "source_timestamp"),
        license=_optional_string(item, "license"),
        content_hash=_optional_string(item, "content_hash"),
        attributes=_attributes(item),
        schema_version=schema_version,
    )


def common_chunk_from_record(item: Mapping[str, Any]) -> CommonChunk:
    """Validate and deserialize a native common chunk record."""

    schema_version = int(item.get("schema_version", COMMON_RECORD_SCHEMA_VERSION))
    if schema_version != COMMON_RECORD_SCHEMA_VERSION:
        raise ValueError(f"Unsupported common chunk schema version: {schema_version}")
    text = _required_string(item, "text")
    heading_path = item.get("heading_path", [])
    if not isinstance(heading_path, list) or any(not isinstance(part, str) for part in heading_path):
        raise ValueError("Common chunk field 'heading_path' must be an array of strings")
    ordinal = item.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ValueError("Common chunk field 'ordinal' must be a nonnegative integer")
    character_count = item.get("character_count", len(text))
    if not isinstance(character_count, int) or isinstance(character_count, bool) or character_count != len(text):
        raise ValueError("Common chunk character_count must equal len(text)")
    token_count = item.get("token_count")
    if token_count is not None and (
        not isinstance(token_count, int) or isinstance(token_count, bool) or token_count < 0
    ):
        raise ValueError("Common chunk token_count must be a nonnegative integer or null")
    return CommonChunk(
        chunk_instance_id=_required_string(item, "chunk_instance_id"),
        content_id=_required_string(item, "content_id"),
        document_id=_required_string(item, "document_id"),
        parent_chunk_id=_optional_string(item, "parent_chunk_id"),
        ordinal=ordinal,
        heading_path=list(heading_path),
        text=text,
        character_count=character_count,
        token_count=token_count,
        previous_chunk_id=_optional_string(item, "previous_chunk_id"),
        next_chunk_id=_optional_string(item, "next_chunk_id"),
        attributes=_attributes(item),
        schema_version=schema_version,
    )


def document_record_to_common(item: Mapping[str, Any]) -> CommonDocument:
    """Read a native common document, falling back to Wikipedia version 1."""

    if "corpus" in item and "attributes" in item:
        return common_document_from_record(item)
    return wikipedia_document_to_common(item)


def chunk_records_to_common(items: Iterable[Mapping[str, Any]]) -> Iterator[CommonChunk]:
    """Read either native common chunks or legacy Wikipedia chunks.

    A single input file may not mix the two formats. Native records stream one
    at a time; legacy Wikipedia records retain their document-sized buffering
    so neighbor links can still be synthesized.
    """

    iterator = iter(items)
    try:
        first = next(iterator)
    except StopIteration:
        return
    native = "chunk_instance_id" in first and "content_id" in first and "attributes" in first
    combined = chain((first,), iterator)
    if native:
        for item in combined:
            if not ("chunk_instance_id" in item and "content_id" in item and "attributes" in item):
                raise ValueError("Chunk input mixes common and legacy record formats")
            yield common_chunk_from_record(item)
        return
    yield from wikipedia_chunks_to_common(combined)


def wikipedia_document_to_common(item: Mapping[str, Any]) -> CommonDocument:
    """Convert a version-1 Wikipedia document record to the common representation."""

    corpus = str(item.get("corpus") or item.get("source") or "wikipedia-en")
    dump_date = item.get("source_version") or item.get("dump_date")
    source_timestamp = item.get("source_timestamp") or item.get("revision_timestamp")
    known = {
        "schema_version",
        "document_id",
        "corpus",
        "source",
        "title",
        "source_url",
        "source_version",
        "dump_date",
        "source_timestamp",
        "revision_timestamp",
        "license",
        "content_hash",
    }
    attributes = dict(item.get("attributes") or {})
    attributes.update({key: value for key, value in item.items() if key not in known})
    return CommonDocument(
        document_id=str(item["document_id"]),
        corpus=corpus,
        title=str(item["title"]),
        source_url=item.get("source_url"),
        source_version=str(dump_date) if dump_date is not None else None,
        source_timestamp=str(source_timestamp) if source_timestamp is not None else None,
        license=item.get("license") or ("CC-BY-SA-4.0" if corpus == "wikipedia-en" else None),
        content_hash=item.get("content_hash"),
        attributes=attributes,
    )


def _chunk_instance_id(item: Mapping[str, Any]) -> str:
    value = item.get("chunk_instance_id") or item.get("chunk_id")
    if value:
        return str(value)
    identity = json.dumps(
        [item.get("document_id"), item.get("ordinal"), item.get("heading_path"), item.get("text")],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def wikipedia_chunks_to_common(items: Iterable[Mapping[str, Any]]) -> Iterator[CommonChunk]:
    """Convert ordered version-1 chunks while adding ordinals and neighbor links.

    Only one document's chunks are buffered. Version-1 chunk IDs are retained as
    instance IDs, while content IDs are derived solely from normalized text.
    """

    buffered: list[Mapping[str, Any]] = []
    current_document: str | None = None

    def emit(group: list[Mapping[str, Any]]) -> Iterator[CommonChunk]:
        ids = [_chunk_instance_id(item) for item in group]
        for ordinal, (item, instance_id) in enumerate(zip(group, ids, strict=True)):
            text = str(item["text"])
            heading_path = item.get("heading_path") or []
            if isinstance(heading_path, str):
                heading_path = [part.strip() for part in heading_path.split(">") if part.strip()]
            known = {
                "schema_version",
                "chunk_instance_id",
                "chunk_id",
                "content_id",
                "content_hash",
                "document_id",
                "parent_chunk_id",
                "ordinal",
                "heading_path",
                "text",
                "character_count",
                "token_count",
                "previous_chunk_id",
                "next_chunk_id",
                "attributes",
            }
            attributes = dict(item.get("attributes") or {})
            attributes.update({key: value for key, value in item.items() if key not in known})
            content_id = item.get("content_id")
            if not content_id:
                legacy_hash = item.get("content_hash")
                content_id = f"sha256:{legacy_hash}" if legacy_hash else make_content_id(text)
            yield CommonChunk(
                chunk_instance_id=instance_id,
                content_id=str(content_id),
                document_id=str(item["document_id"]),
                parent_chunk_id=item.get("parent_chunk_id"),
                ordinal=int(item.get("ordinal", ordinal)),
                heading_path=[str(part) for part in heading_path],
                text=text,
                character_count=int(item.get("character_count", len(text))),
                token_count=int(item["token_count"]) if item.get("token_count") is not None else None,
                previous_chunk_id=item.get("previous_chunk_id") or (ids[ordinal - 1] if ordinal else None),
                next_chunk_id=item.get("next_chunk_id") or (ids[ordinal + 1] if ordinal + 1 < len(ids) else None),
                attributes=attributes,
            )

    for item in items:
        document_id = str(item["document_id"])
        if current_document is not None and document_id != current_document:
            yield from emit(buffered)
            buffered = []
        current_document = document_id
        buffered.append(item)
    if buffered:
        yield from emit(buffered)
