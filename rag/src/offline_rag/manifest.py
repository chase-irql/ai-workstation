from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{40})\s+\*?(.+)$")


def sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def expected_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = CHECKSUM_RE.match(line)
        if match:
            values[match.group(2)] = match.group(1).lower()
    return values


def create_manifest(directory: Path, dump_date: str) -> dict[str, object]:
    prefix = f"enwiki-{dump_date}"
    names = [
        f"{prefix}-pages-articles-multistream.xml.bz2",
        f"{prefix}-pages-articles-multistream-index.txt.bz2",
    ]
    checksum_name = f"{prefix}-sha1sums.txt"
    checksums = expected_checksums(directory / checksum_name)
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
        "files": files,
    }
    temporary = directory / "manifest.json.partial"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "manifest.json")
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
