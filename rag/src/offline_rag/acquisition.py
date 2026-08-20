from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import py7zr

from .dataset_registry import DatasetDefinition, PUBLISHER_CHECKSUM_ALGORITHMS, load_registry


USER_AGENT = "offline-ai-knowledge-ark/0.9 (+local archival acquisition)"
PORTABLE_NAMES_MARKER = ".archive-name-encoding-v1.json"
WINDOWS_INVALID_NAME_CHARS = frozenset('<>:"|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{number}" for number in range(1, 10)} | {f"lpt{number}" for number in range(1, 10)}
)


HASHLIB_ALGORITHMS = {"sha256": "sha256", "sha3-256": "sha3_256"}


def _checksums(path: Path, algorithms: Iterable[str]) -> dict[str, str]:
    requested = tuple(dict.fromkeys(algorithms))
    unknown = set(requested) - set(HASHLIB_ALGORITHMS)
    if unknown:
        raise ValueError(f"Unsupported checksum algorithm(s): {', '.join(sorted(unknown))}")
    digests = {name: hashlib.new(HASHLIB_ALGORITHMS[name]) for name in requested}
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            for digest in digests.values():
                digest.update(block)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _sha256(path: Path) -> str:
    return _checksums(path, ("sha256",))["sha256"]


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _safe_project_path(project_root: Path, relative: str) -> Path:
    root = project_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Dataset path escapes project root: {relative!r}")
    return path


def _dataset(registry: Path, dataset_id: str) -> DatasetDefinition:
    matches = [dataset for dataset in load_registry(registry) if dataset.dataset_id == dataset_id]
    if len(matches) != 1:
        raise ValueError(f"Unknown or duplicate dataset ID: {dataset_id!r}")
    return matches[0]


def _publisher_checksum(dataset: DatasetDefinition) -> tuple[str, str] | None:
    value = dataset.acquisition.get("publisher_checksum")
    if value is None:
        return None
    algorithm = dataset.acquisition.get("publisher_checksum_algorithm", "sha256")
    if not isinstance(algorithm, str) or algorithm not in PUBLISHER_CHECKSUM_ALGORITHMS:
        raise ValueError(
            f"Dataset {dataset.dataset_id!r} has unsupported publisher checksum algorithm {algorithm!r}"
        )
    expected_length = PUBLISHER_CHECKSUM_ALGORITHMS[algorithm]
    if (
        not isinstance(value, str)
        or len(value) != expected_length
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"Dataset {dataset.dataset_id!r} has an invalid publisher {algorithm} checksum")
    return algorithm, value.casefold()


def _archive_name(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    if not name or name in {".", ".."}:
        raise ValueError(f"Cannot determine archive filename from URL: {url}")
    return name


def _download_http(dataset: DatasetDefinition, destination: Path, retries: int = 4) -> dict[str, object]:
    url = str(dataset.acquisition["location"])
    partial = destination.with_suffix(destination.suffix + ".partial")
    publisher = _publisher_checksum(dataset)
    if destination.exists():
        algorithms = ("sha256",) if publisher is None else ("sha256", publisher[0])
        actual = _checksums(destination, algorithms)
        if publisher and actual[publisher[0]] != publisher[1]:
            raise ValueError(f"Existing archive checksum mismatch: {destination}")
        return {
            "path": destination,
            "sha256": actual["sha256"],
            "bytes": destination.stat().st_size,
            "reused": True,
            "publisher_checksum": (
                {"algorithm": publisher[0], "value": actual[publisher[0]], "verified": True}
                if publisher
                else None
            ),
        }
    partial.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                status = getattr(response, "status", response.getcode())
                if existing and status != 206:
                    raise RuntimeError(
                        f"Server ignored Range resume for {partial}; preserve it and restart explicitly in a new directory"
                    )
                content_length = response.headers.get("Content-Length")
                remaining = int(content_length) if content_length else None
                expected_total = existing + remaining if remaining is not None else None
                if expected_total is not None and expected_total > dataset.storage["download_max_bytes"]:
                    raise RuntimeError(
                        f"Server reports {expected_total} bytes, above registry ceiling "
                        f"{dataset.storage['download_max_bytes']}"
                    )
                free = shutil.disk_usage(partial.parent).free
                required = remaining or dataset.storage["download_max_bytes"]
                if free < required + 1024 * 1024 * 1024:
                    raise OSError(f"Insufficient free space for {dataset.dataset_id}: need {required} bytes plus reserve")
                mode = "ab" if existing else "xb"
                with partial.open(mode) as stream:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            actual_size = partial.stat().st_size
            if actual_size < dataset.storage["download_min_bytes"] or actual_size > dataset.storage["download_max_bytes"]:
                raise ValueError(
                    f"Downloaded size {actual_size} is outside registry range "
                    f"{dataset.storage['download_min_bytes']}..{dataset.storage['download_max_bytes']}"
                )
            algorithms = ("sha256",) if publisher is None else ("sha256", publisher[0])
            actual = _checksums(partial, algorithms)
            if publisher and actual[publisher[0]] != publisher[1]:
                raise ValueError(f"Publisher {publisher[0]} mismatch for {destination.name}")
            os.replace(partial, destination)
            return {
                "path": destination,
                "sha256": actual["sha256"],
                "bytes": actual_size,
                "reused": False,
                "publisher_checksum": (
                    {"algorithm": publisher[0], "value": actual[publisher[0]], "verified": True}
                    if publisher
                    else None
                ),
            }
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == retries:
                raise RuntimeError(f"Download failed after {retries} attempts: {url}") from error
            time.sleep(min(2 ** (attempt - 1), 30))
    raise AssertionError("unreachable")


def _safe_archive_member(root: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise ValueError(f"Archive contains an absolute path: {name!r}")
    path = (root / normalized).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Archive member escapes extraction directory: {name!r}")
    return path


def _portable_archive_name(name: str) -> tuple[str, bool]:
    """Encode archive names that NTFS cannot represent, reversibly per segment."""

    normalized = name.replace("\\", "/")
    changed = False
    encoded_parts: list[str] = []
    for part in normalized.split("/"):
        output: list[str] = []
        for character in part:
            if character == "%" or character in WINDOWS_INVALID_NAME_CHARS or ord(character) < 32 or "A" <= character <= "Z":
                output.extend(f"%{byte:02X}" for byte in character.encode("utf-8"))
                changed = True
            else:
                output.append(character)
        encoded = "".join(output)
        while encoded.endswith((".", " ")):
            character = encoded[-1]
            encoded = encoded[:-1] + f"%{ord(character):02X}"
            changed = True
        if encoded.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES and encoded:
            first = encoded[0]
            encoded = f"%{ord(first):02X}" + encoded[1:]
            changed = True
        encoded_parts.append(encoded)
    return "/".join(encoded_parts), changed


def _write_portable_names_marker(root: Path, encoded_members: int) -> None:
    marker = root / PORTABLE_NAMES_MARKER
    with marker.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            {
                "schema_version": 1,
                "encoding": "percent-encode-ntfs-invalid-and-ascii-uppercase-utf8-bytes",
                "encoded_members": encoded_members,
            },
            stream,
            sort_keys=True,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _validate_tar_link(root: Path, member: tarfile.TarInfo) -> None:
    """Allow only links whose normalized target remains inside the archive root."""

    link = member.linkname.replace("\\", "/")
    if not link or link.startswith("/") or re.match(r"^[A-Za-z]:", link):
        raise ValueError(f"Archive link has an absolute or empty target: {member.name!r} -> {member.linkname!r}")
    if member.issym():
        base = posixpath.dirname(member.name.replace("\\", "/"))
        normalized = posixpath.normpath(posixpath.join(base, link))
    else:
        normalized = posixpath.normpath(link)
    _safe_archive_member(root, normalized)


def extract_archive(archive: Path, output: Path) -> dict[str, object]:
    """Validate and atomically extract a ZIP, tar, or 7z archive."""

    if not archive.is_file():
        raise FileNotFoundError(archive)
    if output.exists():
        raise FileExistsError(f"Extraction output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.extracting-", dir=output.parent))
    files = 0
    extracted_bytes = 0
    skipped_links = 0
    encoded_members = 0
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as bundle:
                corrupt = bundle.testzip()
                if corrupt:
                    raise ValueError(f"ZIP integrity check failed at {corrupt!r}")
                for info in bundle.infolist():
                    _safe_archive_member(temporary, info.filename)
                    portable_name, changed = _portable_archive_name(info.filename)
                    encoded_members += int(changed)
                    target = _safe_archive_member(temporary, portable_name)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info) as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    files += 1
                    extracted_bytes += target.stat().st_size
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive, mode="r:*") as bundle:
                members = bundle.getmembers()
                for member in members:
                    _safe_archive_member(temporary, member.name)
                    if member.isdev():
                        raise ValueError(f"Archive contains an unsupported device: {member.name!r}")
                    if member.issym() or member.islnk():
                        _validate_tar_link(temporary, member)
                        skipped_links += 1
                        continue
                    portable_name, changed = _portable_archive_name(member.name)
                    encoded_members += int(changed)
                    target = _safe_archive_member(temporary, portable_name)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        source = bundle.extractfile(member)
                        if source is None:
                            raise ValueError(f"Unable to read tar member: {member.name!r}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source, target.open("xb") as destination:
                            shutil.copyfileobj(source, destination, length=1024 * 1024)
                        files += 1
                        extracted_bytes += member.size
        elif archive.suffix.casefold() == ".7z":
            with py7zr.SevenZipFile(archive, mode="r") as bundle:
                if bundle.needs_password():
                    raise ValueError("Encrypted 7z archives are unsupported")
                members = bundle.list()
                for member in members:
                    _safe_archive_member(temporary, member.filename)
                    if member.is_symlink:
                        raise ValueError(f"7z archive contains an unsupported link: {member.filename!r}")
                    if member.is_file:
                        files += 1
                        extracted_bytes += int(member.uncompressed)
                bundle.extractall(path=temporary)
            for path in temporary.rglob("*"):
                if path.is_symlink():
                    raise ValueError(f"7z extraction created an unsupported link: {path}")
        else:
            raise ValueError(f"Unsupported or invalid archive: {archive}")
        if encoded_members:
            _write_portable_names_marker(temporary, encoded_members)
        os.replace(temporary, output)
        return {
            "path": str(output.resolve()),
            "files": files,
            "bytes": extracted_bytes,
            "skipped_archive_links": skipped_links,
            "portable_encoded_members": encoded_members,
        }
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def validate_extraction(archive: Path, output: Path) -> dict[str, object]:
    """Verify an existing extracted tree against its source archive."""

    if not output.is_dir():
        raise NotADirectoryError(output)
    actual_files = {
        path.relative_to(output).as_posix(): path
        for path in output.rglob("*")
        if path.is_file() and path.name != PORTABLE_NAMES_MARKER
    }
    expected_sizes: dict[str, int] = {}
    encoded_members = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            corrupt = bundle.testzip()
            if corrupt:
                raise ValueError(f"ZIP integrity check failed at {corrupt!r}")
            expected_crc: dict[str, int] = {}
            for info in bundle.infolist():
                _safe_archive_member(output, info.filename)
                normalized, changed = _portable_archive_name(info.filename)
                encoded_members += int(changed)
                if info.is_dir():
                    continue
                _safe_archive_member(output, normalized)
                expected_sizes[normalized] = info.file_size
                expected_crc[normalized] = info.CRC
            if set(actual_files) != set(expected_sizes):
                raise ValueError("Existing extraction file set does not match ZIP archive")
            for name, path in actual_files.items():
                if path.stat().st_size != expected_sizes[name]:
                    raise ValueError(f"Existing extraction size mismatch: {name}")
                checksum = 0
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        checksum = zlib.crc32(block, checksum)
                if checksum & 0xFFFFFFFF != expected_crc[name]:
                    raise ValueError(f"Existing extraction CRC mismatch: {name}")
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive, mode="r:*") as bundle:
            for member in bundle.getmembers():
                if member.isdev():
                    raise ValueError(f"Archive contains an unsupported device: {member.name!r}")
                if member.issym() or member.islnk():
                    _validate_tar_link(output, member)
                    continue
                normalized, changed = _portable_archive_name(member.name)
                encoded_members += int(changed)
                if member.isfile():
                    _safe_archive_member(output, normalized)
                    expected_sizes[normalized] = member.size
            if set(actual_files) != set(expected_sizes):
                raise ValueError("Existing extraction file set does not match tar archive")
            for name, path in actual_files.items():
                if path.stat().st_size != expected_sizes[name]:
                    raise ValueError(f"Existing extraction size mismatch: {name}")
    elif archive.suffix.casefold() == ".7z":
        with py7zr.SevenZipFile(archive, mode="r") as bundle:
            if bundle.needs_password():
                raise ValueError("Encrypted 7z archives are unsupported")
            for member in bundle.list():
                _safe_archive_member(output, member.filename)
                if member.is_symlink:
                    raise ValueError(f"7z archive contains an unsupported link: {member.filename!r}")
                if member.is_file:
                    expected_sizes[member.filename.replace("\\", "/")] = int(member.uncompressed)
        if set(actual_files) != set(expected_sizes):
            raise ValueError("Existing extraction file set does not match 7z archive")
        for name, path in actual_files.items():
            if path.is_symlink() or path.stat().st_size != expected_sizes[name]:
                raise ValueError(f"Existing extraction size or type mismatch: {name}")
    else:
        raise ValueError(f"Unsupported or invalid archive: {archive}")
    marker = output / PORTABLE_NAMES_MARKER
    if encoded_members and not marker.is_file():
        raise ValueError("Existing extraction is missing its portable-name encoding marker")
    if marker.is_file():
        value = json.loads(marker.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("encoded_members") != encoded_members:
            raise ValueError("Existing extraction has an invalid portable-name encoding marker")
    skipped_links = 0
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, mode="r:*") as bundle:
            skipped_links = sum(member.issym() or member.islnk() for member in bundle.getmembers())
    return {
        "path": str(output.resolve()),
        "files": len(actual_files),
        "bytes": sum(path.stat().st_size for path in actual_files.values()),
        "skipped_archive_links": skipped_links,
        "portable_encoded_members": encoded_members,
    }


def acquire_dataset(
    registry: Path,
    dataset_id: str,
    project_root: Path,
    *,
    extract: bool = False,
) -> dict[str, object]:
    dataset = _dataset(registry, dataset_id)
    if dataset.acquisition.get("method") != "http":
        raise ValueError(
            f"Dataset {dataset_id!r} uses {dataset.acquisition.get('method')!r}; "
            "this command only automates resumable HTTP acquisitions"
        )
    raw = _safe_project_path(project_root, dataset.paths["raw"])
    raw.mkdir(parents=True, exist_ok=True)
    url = str(dataset.acquisition["location"])
    archive = raw / _archive_name(url)
    acquired = _download_http(dataset, archive)
    extracted: dict[str, object] | None = None
    if extract:
        extraction = raw / "extracted"
        if extraction.exists():
            existing_manifest_path = raw / "acquisition-manifest.json"
            if existing_manifest_path.is_file():
                existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
                existing_sha256 = ((existing_manifest.get("archive") or {}).get("sha256"))
                if existing_manifest.get("status") != "extracted" or existing_sha256 != acquired["sha256"]:
                    raise ValueError(f"Existing extraction does not match the acquired archive: {extraction}")
            extracted = validate_extraction(archive, extraction)
            extracted["reused"] = True
        else:
            extracted = extract_archive(archive, extraction)
            extracted["reused"] = False
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "official_source_url": dataset.official_source_url,
        "download_url": url,
        "release": dataset.release,
        "license": dataset.license,
        "attribution": dataset.attribution,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "status": "extracted" if extracted else "validated",
        "integrity": {
            "archive_sha256": acquired["sha256"],
            "publisher_checksum_verified": acquired["publisher_checksum"] is not None,
            "publisher_checksum": acquired["publisher_checksum"],
            "archive_structure_validated": bool(extracted),
        },
        "archive": {
            "name": archive.name,
            "bytes": acquired["bytes"],
            "sha256": acquired["sha256"],
        },
        "extraction": extracted,
    }
    _atomic_json(raw / "acquisition-manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acquire one small registered corpus with resume and validation.")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--extract", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = acquire_dataset(args.registry, args.dataset, args.project_root, extract=args.extract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
