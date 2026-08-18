from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{40})\s+\*?(.+)$")
DUMP_DATE_RE = re.compile(r"^\d{8}$")


def sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def expected_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    values: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = CHECKSUM_RE.match(line)
        if not match:
            raise ValueError(f"Malformed checksum entry in {path} at line {line_number}")
        name = match.group(2)
        digest = match.group(1).lower()
        if name in values and values[name] != digest:
            raise ValueError(f"Conflicting checksum entries for {name}")
        values[name] = digest
    return values


def atomic_write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def create_manifest(directory: Path, dump_date: str) -> dict[str, object]:
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    if not DUMP_DATE_RE.fullmatch(dump_date):
        raise ValueError("dump_date must contain exactly eight digits")
    prefix = f"enwiki-{dump_date}"
    names = [
        f"{prefix}-pages-articles-multistream.xml.bz2",
        f"{prefix}-pages-articles-multistream-index.txt.bz2",
    ]
    checksum_name = f"{prefix}-sha1sums.txt"
    checksum_path = directory / checksum_name
    checksums = expected_checksums(checksum_path)
    files = []
    for name in names:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(path)
        expected = checksums.get(name)
        if not expected:
            raise ValueError(f"No SHA1 entry for {name}")
        actual = sha1(path)
        if actual != expected:
            raise ValueError(f"SHA1 mismatch for {name}: expected {expected}, got {actual}")
        files.append({"name": name, "bytes": path.stat().st_size, "sha1": actual, "verified": True})
    manifest = {
        "schema_version": 1,
        "corpus": "English Wikipedia articles",
        "dump": prefix,
        "source": f"https://dumps.wikimedia.org/enwiki/{dump_date}/",
        "format": "MediaWiki XML, concatenated bzip2 multistream",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "checksum_file": {
            "name": checksum_name,
            "sha256": hashlib.sha256(checksum_path.read_bytes()).hexdigest(),
        },
        "files": files,
    }
    atomic_write_json(directory / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Wikipedia dump and write its provenance manifest.")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--dump-date", required=True)
    args = parser.parse_args()
    print(json.dumps(create_manifest(args.directory, args.dump_date), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
