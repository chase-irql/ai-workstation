from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from .dataset_registry import DatasetDefinition, load_registry


RSYNC_MANIFEST_SCHEMA_VERSION = 1
FILE_INVENTORY_NAME = "files.sha256.jsonl"
SNAPSHOT_MANIFEST_NAME = "snapshot-manifest.json"


def _dataset(registry: Path, dataset_id: str) -> DatasetDefinition:
    matches = [item for item in load_registry(registry) if item.dataset_id == dataset_id]
    if len(matches) != 1:
        raise ValueError(f"Unknown or duplicate dataset ID: {dataset_id!r}")
    dataset = matches[0]
    if dataset.acquisition.get("method") != "rsync":
        raise ValueError(f"Dataset {dataset_id!r} is not configured for rsync acquisition")
    return dataset


def _safe_project_path(project_root: Path, relative: str) -> Path:
    root = project_root.resolve()
    value = (root / relative).resolve()
    if not value.is_relative_to(root):
        raise ValueError(f"Dataset path escapes project root: {relative!r}")
    return value


def windows_path_to_wsl(path: Path) -> str:
    """Translate a resolved drive-letter Windows path for WSL rsync."""

    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").casefold()
    if len(drive) != 1 or not drive.isalpha():
        raise ValueError(f"WSL acquisition requires a drive-letter path: {resolved}")
    relative = resolved.as_posix().split(":", 1)[1].lstrip("/")
    return f"/mnt/{drive}/{relative}"


def _resolved_source(source: str) -> tuple[str, str]:
    parsed = urlparse(source)
    if parsed.scheme != "rsync" or not parsed.hostname or not parsed.path:
        raise ValueError(f"Invalid rsync source URL: {source!r}")
    address = socket.gethostbyname(parsed.hostname)
    netloc = address if parsed.port is None else f"{address}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")), address


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _source_files(root: Path) -> list[Path]:
    excluded = {FILE_INVENTORY_NAME, SNAPSHOT_MANIFEST_NAME}
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name not in excluded and ".rsync-partial" not in path.parts
    ]
    files.sort(key=lambda item: item.relative_to(root).as_posix())
    return files


def write_inventory(root: Path) -> dict[str, Any]:
    """Write a deterministic per-file inventory and return aggregate identity."""

    inventory = root / FILE_INVENTORY_NAME
    tree = hashlib.sha256()
    total_bytes = 0
    files = _source_files(root)
    with inventory.open("w", encoding="utf-8", newline="\n") as stream:
        for path in files:
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            item = {"path": relative, "bytes": size, "sha256": _sha256(path)}
            line = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write(line + "\n")
            tree.update((line + "\n").encode("utf-8"))
            total_bytes += size
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "files": len(files),
        "bytes": total_bytes,
        "tree_sha256": tree.hexdigest(),
        "inventory_sha256": _sha256(inventory),
    }


def validate_snapshot(root: Path) -> dict[str, Any]:
    """Validate every file against a published snapshot inventory."""

    manifest_path = root / SNAPSHOT_MANIFEST_NAME
    inventory_path = root / FILE_INVENTORY_NAME
    if not manifest_path.is_file() or not inventory_path.is_file():
        raise ValueError(f"Snapshot manifests are missing under {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != RSYNC_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported rsync snapshot manifest")
    if _sha256(inventory_path) != manifest.get("inventory_sha256"):
        raise ValueError("Rsync snapshot inventory checksum mismatch")
    expected: dict[str, tuple[int, str]] = {}
    tree = hashlib.sha256()
    for raw_line in inventory_path.read_text(encoding="utf-8").splitlines(keepends=True):
        tree.update(raw_line.encode("utf-8"))
        item = json.loads(raw_line)
        expected[str(item["path"])] = (int(item["bytes"]), str(item["sha256"]))
    actual = {path.relative_to(root).as_posix(): path for path in _source_files(root)}
    if set(actual) != set(expected):
        raise ValueError("Rsync snapshot file set differs from its inventory")
    total_bytes = 0
    for relative, path in actual.items():
        size, checksum = expected[relative]
        if path.stat().st_size != size or _sha256(path) != checksum:
            raise ValueError(f"Rsync snapshot file validation failed: {relative}")
        total_bytes += size
    if tree.hexdigest() != manifest.get("tree_sha256"):
        raise ValueError("Rsync snapshot tree identity mismatch")
    if len(actual) != manifest.get("files") or total_bytes != manifest.get("bytes"):
        raise ValueError("Rsync snapshot aggregate counts differ from its manifest")
    return manifest


def acquire_rsync_snapshot(
    registry: Path,
    dataset_id: str,
    project_root: Path,
    *,
    snapshot: str,
    distribution: str = "Ubuntu",
) -> dict[str, Any]:
    """Acquire, inventory, and atomically publish one immutable rsync snapshot."""

    dataset = _dataset(registry, dataset_id)
    if not snapshot or any(character not in "0123456789-" for character in snapshot):
        raise ValueError("snapshot must contain only digits and hyphens")
    raw = _safe_project_path(project_root, dataset.paths["raw"])
    raw.mkdir(parents=True, exist_ok=True)
    final = raw / f"snapshot-{snapshot}"
    partial = raw / f".snapshot-{snapshot}.partial"
    if final.exists():
        result = validate_snapshot(final)
        result["reused"] = True
        return result
    partial.mkdir(parents=True, exist_ok=True)
    source = str(dataset.acquisition["location"])
    resolved_source, address = _resolved_source(source)
    target = windows_path_to_wsl(partial).rstrip("/") + "/"
    command = [
        "wsl.exe",
        "-d",
        distribution,
        "--",
        "rsync",
        "-az",
        "--no-links",
        "--partial",
        "--partial-dir=.rsync-partial",
        "--delete-delay",
        "--stats",
        resolved_source.rstrip("/") + "/",
        target,
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise RuntimeError(f"rsync acquisition failed; resumable partial retained at {partial}: {detail}")
    partial_directory = partial / ".rsync-partial"
    if partial_directory.exists():
        if any(partial_directory.rglob("*")):
            raise RuntimeError(f"rsync reported success but partial transfers remain under {partial_directory}")
        partial_directory.rmdir()
    inventory = write_inventory(partial)
    minimum = int(dataset.storage["download_min_bytes"])
    maximum = int(dataset.storage["download_max_bytes"])
    if not minimum <= inventory["bytes"] <= maximum:
        raise ValueError(
            f"Snapshot size {inventory['bytes']} is outside registry range {minimum}..{maximum}; partial retained"
        )
    manifest = {
        "schema_version": RSYNC_MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "release": f"snapshot-{snapshot}",
        "source": source,
        "resolved_address": address,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "license": dataset.license,
        "attribution": dataset.attribution,
        "rsync_links_omitted": True,
        **inventory,
    }
    manifest_path = partial / SNAPSHOT_MANIFEST_NAME
    with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, final)
    manifest["path"] = str(final.resolve())
    manifest["reused"] = False
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire an immutable, verified rsync corpus snapshot through WSL.")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--distribution", default="Ubuntu")
    args = parser.parse_args(argv)
    result = acquire_rsync_snapshot(
        args.registry,
        args.dataset,
        args.project_root,
        snapshot=args.snapshot,
        distribution=args.distribution,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
