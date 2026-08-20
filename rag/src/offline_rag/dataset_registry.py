from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REGISTRY_SCHEMA_VERSION = 1
DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
STAGES = ("planned", "downloaded", "validated", "extracted", "parsed", "indexed", "evaluated")
ACQUISITION_METHODS = (
    "http",
    "http-file-set",
    "http-catalog-file-set",
    "git",
    "rsync",
    "official-export",
    "manual",
)
PUBLISHER_CHECKSUM_ALGORITHMS = {"sha256": 64, "sha3-256": 64}


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    name: str
    description: str
    category: str
    official_source_url: str
    license: str
    attribution: str
    release: str
    update_frequency: str
    scope: str
    formats: tuple[str, ...]
    acquisition: dict[str, Any]
    storage: dict[str, int]
    paths: dict[str, str]
    status: str
    notes: str


def _string(item: Mapping[str, Any], field: str, *, allow_empty: bool = False) -> str:
    value = item.get(field)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Dataset field {field!r} must be a nonempty string")
    return value


def _url(item: Mapping[str, Any], field: str) -> str:
    value = _string(item, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "rsync"} or not parsed.netloc:
        raise ValueError(f"Dataset field {field!r} must be an HTTPS or rsync URL")
    return value


def _storage(item: Mapping[str, Any]) -> dict[str, int]:
    value = item.get("storage")
    if not isinstance(value, Mapping):
        raise ValueError("Dataset field 'storage' must be an object")
    names = ("download_min_bytes", "download_max_bytes", "extracted_max_bytes", "indexed_max_bytes")
    result: dict[str, int] = {}
    for name in names:
        number = value.get(name)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ValueError(f"Dataset storage field {name!r} must be a nonnegative integer")
        result[name] = number
    if result["download_min_bytes"] > result["download_max_bytes"]:
        raise ValueError("Dataset download_min_bytes exceeds download_max_bytes")
    if result["extracted_max_bytes"] < result["download_min_bytes"]:
        raise ValueError("Dataset extracted_max_bytes is implausibly smaller than download_min_bytes")
    return result


def _paths(item: Mapping[str, Any]) -> dict[str, str]:
    value = item.get("paths")
    if not isinstance(value, Mapping):
        raise ValueError("Dataset field 'paths' must be an object")
    result: dict[str, str] = {}
    for name in ("raw", "processed", "index"):
        raw = value.get(name)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"Dataset path {name!r} must be a nonempty relative path")
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Dataset path {name!r} must stay within the project root")
        result[name] = path.as_posix()
    return result


def validate_dataset(item: Mapping[str, Any]) -> DatasetDefinition:
    dataset_id = _string(item, "dataset_id")
    if not DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError(f"Invalid dataset_id: {dataset_id!r}")
    formats = item.get("formats")
    if not isinstance(formats, list) or not formats or any(not isinstance(value, str) or not value for value in formats):
        raise ValueError(f"Dataset {dataset_id!r} formats must be a nonempty string array")
    acquisition = item.get("acquisition")
    if not isinstance(acquisition, Mapping):
        raise ValueError(f"Dataset {dataset_id!r} acquisition must be an object")
    method = acquisition.get("method")
    if method not in ACQUISITION_METHODS:
        raise ValueError(f"Dataset {dataset_id!r} has unsupported acquisition method {method!r}")
    location = acquisition.get("location")
    if not isinstance(location, str) or not location:
        raise ValueError(f"Dataset {dataset_id!r} acquisition location must be nonempty")
    parsed_location = urlparse(location)
    if parsed_location.scheme not in {"https", "rsync"} or not parsed_location.netloc:
        raise ValueError(f"Dataset {dataset_id!r} acquisition location must be an HTTPS or rsync URL")
    if method == "http-file-set":
        assets = acquisition.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ValueError(f"Dataset {dataset_id!r} HTTP file set must declare a nonempty assets array")
        seen_names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, Mapping):
                raise ValueError(f"Dataset {dataset_id!r} HTTP file-set assets must be objects")
            asset_url = asset.get("url")
            parsed_asset_url = urlparse(asset_url) if isinstance(asset_url, str) else None
            if not parsed_asset_url or parsed_asset_url.scheme != "https" or not parsed_asset_url.netloc:
                raise ValueError(f"Dataset {dataset_id!r} HTTP file-set asset URL must use HTTPS")
            filename = asset.get("filename")
            if (
                not isinstance(filename, str)
                or not filename
                or Path(filename).name != filename
                or filename in {".", ".."}
            ):
                raise ValueError(f"Dataset {dataset_id!r} HTTP file-set asset filename must be a basename")
            folded_name = filename.casefold()
            if folded_name in seen_names:
                raise ValueError(f"Dataset {dataset_id!r} HTTP file set contains duplicate filenames")
            seen_names.add(folded_name)
            minimum = asset.get("min_bytes")
            maximum = asset.get("max_bytes")
            if (
                not isinstance(minimum, int)
                or isinstance(minimum, bool)
                or minimum < 0
                or not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or maximum < minimum
            ):
                raise ValueError(f"Dataset {dataset_id!r} HTTP file-set asset has invalid byte bounds")
    if method == "http-catalog-file-set":
        asset_url_prefix = acquisition.get("asset_url_prefix")
        parsed_prefix = urlparse(asset_url_prefix) if isinstance(asset_url_prefix, str) else None
        if (
            not parsed_prefix
            or parsed_prefix.scheme != "https"
            or not parsed_prefix.netloc
            or not asset_url_prefix.endswith("/")
            or parsed_prefix.query
            or parsed_prefix.fragment
        ):
            raise ValueError(
                f"Dataset {dataset_id!r} HTTP catalog asset_url_prefix must be a query-free HTTPS directory URL"
            )
        asset_path_pattern = acquisition.get("asset_path_pattern")
        if not isinstance(asset_path_pattern, str) or not asset_path_pattern.startswith("^") or not asset_path_pattern.endswith("$"):
            raise ValueError(
                f"Dataset {dataset_id!r} HTTP catalog asset_path_pattern must be an anchored regular expression"
            )
        try:
            re.compile(asset_path_pattern)
        except re.error as error:
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog asset_path_pattern is invalid") from error
        for field in ("min_assets", "max_assets", "asset_min_bytes", "asset_max_bytes", "max_concurrency"):
            value = acquisition.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"Dataset {dataset_id!r} HTTP catalog field {field!r} must be a positive integer")
        if acquisition["min_assets"] > acquisition["max_assets"]:
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog min_assets exceeds max_assets")
        if acquisition["asset_min_bytes"] > acquisition["asset_max_bytes"]:
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog asset_min_bytes exceeds asset_max_bytes")
        if acquisition["max_concurrency"] > 16:
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog max_concurrency must not exceed 16")
        excluded = acquisition.get("excluded_relative_paths", [])
        if not isinstance(excluded, list) or any(not isinstance(value, str) for value in excluded):
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog excluded_relative_paths must be a string array")
        seen_excluded: set[str] = set()
        for relative in excluded:
            path = Path(relative)
            folded = relative.casefold()
            if (
                not relative
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in relative
                or folded in seen_excluded
            ):
                raise ValueError(f"Dataset {dataset_id!r} HTTP catalog contains an unsafe or duplicate exclusion")
            seen_excluded.add(folded)
        magic = acquisition.get("asset_magic")
        if magic is not None and (not isinstance(magic, str) or not 1 <= len(magic.encode("utf-8")) <= 32):
            raise ValueError(f"Dataset {dataset_id!r} HTTP catalog asset_magic must contain 1..32 UTF-8 bytes")
        collection_titles = acquisition.get("collection_titles")
        if collection_titles is not None:
            if not isinstance(collection_titles, Mapping) or not collection_titles:
                raise ValueError(f"Dataset {dataset_id!r} HTTP catalog collection_titles must be a nonempty object")
            for key, title in collection_titles.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or Path(key).name != key
                    or not isinstance(title, str)
                    or not title.strip()
                ):
                    raise ValueError(f"Dataset {dataset_id!r} HTTP catalog collection_titles is invalid")
    publisher_checksum = acquisition.get("publisher_checksum")
    publisher_algorithm = acquisition.get("publisher_checksum_algorithm", "sha256")
    if publisher_checksum is not None:
        if (
            not isinstance(publisher_algorithm, str)
            or publisher_algorithm not in PUBLISHER_CHECKSUM_ALGORITHMS
        ):
            raise ValueError(
                f"Dataset {dataset_id!r} has unsupported publisher checksum algorithm {publisher_algorithm!r}"
            )
        expected_length = PUBLISHER_CHECKSUM_ALGORITHMS[publisher_algorithm]
        if (
            not isinstance(publisher_checksum, str)
            or len(publisher_checksum) != expected_length
            or any(character not in "0123456789abcdefABCDEF" for character in publisher_checksum)
        ):
            raise ValueError(
                f"Dataset {dataset_id!r} has an invalid publisher {publisher_algorithm} checksum"
            )
    elif "publisher_checksum_algorithm" in acquisition:
        raise ValueError(
            f"Dataset {dataset_id!r} declares a publisher checksum algorithm without a checksum"
        )
    status = _string(item, "status")
    if status not in STAGES:
        raise ValueError(f"Dataset {dataset_id!r} has invalid status {status!r}")
    return DatasetDefinition(
        dataset_id=dataset_id,
        name=_string(item, "name"),
        description=_string(item, "description"),
        category=_string(item, "category"),
        official_source_url=_url(item, "official_source_url"),
        license=_string(item, "license"),
        attribution=_string(item, "attribution"),
        release=_string(item, "release"),
        update_frequency=_string(item, "update_frequency"),
        scope=_string(item, "scope"),
        formats=tuple(formats),
        acquisition=dict(acquisition),
        storage=_storage(item),
        paths=_paths(item),
        status=status,
        notes=_string(item, "notes", allow_empty=True),
    )


def load_registry(path: Path) -> tuple[DatasetDefinition, ...]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("Dataset registry must contain an object")
    if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported dataset registry schema version: {value.get('schema_version')!r}")
    items = value.get("datasets")
    if not isinstance(items, list) or not items:
        raise ValueError("Dataset registry must contain at least one dataset")
    datasets = tuple(validate_dataset(item) for item in items if isinstance(item, Mapping))
    if len(datasets) != len(items):
        raise ValueError("Every dataset registry entry must be an object")
    identifiers = [item.dataset_id for item in datasets]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Dataset registry contains duplicate dataset IDs")
    return datasets


def storage_summary(datasets: Sequence[DatasetDefinition]) -> dict[str, int]:
    return {
        key: sum(dataset.storage[key] for dataset in datasets)
        for key in ("download_min_bytes", "download_max_bytes", "extracted_max_bytes", "indexed_max_bytes")
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and summarize the offline corpus dataset registry.")
    parser.add_argument("--registry", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    datasets = load_registry(args.registry)
    print(
        json.dumps(
            {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "datasets": len(datasets),
                "dataset_ids": [dataset.dataset_id for dataset in datasets],
                "storage": storage_summary(datasets),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
