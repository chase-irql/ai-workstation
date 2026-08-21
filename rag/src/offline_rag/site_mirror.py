from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .dataset_registry import load_registry


SITE_MIRROR_SCHEMA_VERSION = 1
USER_AGENT = "OfflineKnowledgeArk/1.0 (+local documentation preservation)"
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() not in {"a", "area"}:
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


@dataclass(frozen=True)
class MirroredPage:
    url: str
    relative_path: str
    byte_count: int
    sha256: str
    links: tuple[str, ...]


@dataclass(frozen=True)
class SkippedPage:
    url: str
    status: int


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _canonical_url(url: str, allowed_prefix: str, content_variant: str = "html") -> str | None:
    parsed = urlsplit(url)
    allowed = urlsplit(allowed_prefix)
    if parsed.scheme.casefold() != allowed.scheme.casefold() or parsed.netloc.casefold() != allowed.netloc.casefold():
        return None
    path = posixpath.normpath(parsed.path or "/")
    if parsed.path.endswith("/") and not path.endswith("/"):
        path += "/"
    if content_variant == "markdown":
        base = allowed.path.rstrip("/")
        folded_path = path.casefold()
        folded_base = base.casefold()
        if folded_path == folded_base:
            path = f"{path}.md"
        elif folded_path == f"{folded_base}/":
            path = f"{path.rstrip('/')}.md"
        elif folded_path == f"{folded_base}.md":
            pass
        elif folded_path.startswith(f"{folded_base}/"):
            if not folded_path.endswith(".md"):
                path = f"{path}.md"
        else:
            return None
        if not path.casefold().endswith(".md"):
            return None
        return urlunsplit((allowed.scheme, allowed.netloc, path, "", ""))
    if path.casefold().endswith("/index.html"):
        path = path[: -len("index.html")]
    if not path.startswith(allowed.path):
        return None
    suffix = posixpath.splitext(path.rstrip("/").rsplit("/", 1)[-1])[1].casefold()
    if not path.endswith("/") and suffix not in {"", ".html", ".htm", ".xhtml"}:
        return None
    return urlunsplit((allowed.scheme, allowed.netloc, path, "", ""))


def _safe_segment(segment: str) -> str:
    result: list[str] = []
    for character in unquote(segment):
        if character in '<>:"/\\|?*' or ord(character) < 32 or character == "%":
            result.extend(f"%{byte:02X}" for byte in character.encode("utf-8"))
        else:
            result.append(character)
    value = "".join(result).rstrip(". ")
    return value or "_"


def _relative_path(url: str, allowed_prefix: str, content_variant: str = "html") -> str:
    parsed = urlsplit(url)
    allowed = urlsplit(allowed_prefix)
    if content_variant == "markdown":
        base = allowed.path.rstrip("/")
        if parsed.path.casefold() == f"{base.casefold()}.md":
            return "index.md"
        relative = parsed.path[len(base) :].lstrip("/")
    else:
        relative = parsed.path[len(allowed.path) :]
    segments = [_safe_segment(segment) for segment in relative.split("/") if segment]
    if parsed.path.endswith("/") or not segments:
        segments.append("index.html")
    elif not posixpath.splitext(segments[-1])[1]:
        segments[-1] += ".html"
    return "/".join(segments)


def _fetch_page(
    url: str,
    allowed_prefix: str,
    *,
    content_variant: str = "html",
    timeout: float = 60.0,
    retries: int = 3,
) -> tuple[MirroredPage | SkippedPage, bytes]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            accept = "text/markdown,text/plain" if content_variant == "markdown" else "text/html,application/xhtml+xml"
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
            with urlopen(request, timeout=timeout) as response:
                final_url = _canonical_url(response.geturl(), allowed_prefix, content_variant)
                if final_url is None:
                    raise ValueError(f"Redirect escaped the configured site prefix: {response.geturl()}")
                content_type = (response.headers.get_content_type() or "").casefold()
                allowed_types = {"text/markdown", "text/plain"} if content_variant == "markdown" else {"text/html", "application/xhtml+xml"}
                if content_type not in allowed_types:
                    raise ValueError(f"Unexpected content type {content_type!r} for {url}")
                data = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            decoded = data.decode(charset, errors="replace")
            if content_variant == "markdown":
                discovered = (match.group(1) for match in MARKDOWN_LINK_RE.finditer(decoded))
            else:
                parser = _LinkParser()
                parser.feed(decoded)
                discovered = iter(parser.links)
            links = {
                normalized
                for href in discovered
                if (normalized := _canonical_url(urljoin(final_url, href), allowed_prefix, content_variant)) is not None
            }
            return MirroredPage(
                url=final_url,
                relative_path=_relative_path(final_url, allowed_prefix, content_variant),
                byte_count=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                links=tuple(sorted(links)),
            ), data
        except HTTPError as error:
            if error.code in {404, 410}:
                return SkippedPage(url=url, status=error.code), b""
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
        except (URLError, TimeoutError, ValueError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last_error is not None
    raise RuntimeError(f"Failed to acquire {url}: {last_error}") from last_error


def _recognized_output(path: Path) -> bool:
    manifest = path / "site-acquisition-manifest.json"
    if not manifest.is_file():
        return False
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("schema_version") == SITE_MIRROR_SCHEMA_VERSION
    except (OSError, ValueError):
        return False


def mirror_site(
    *,
    location: str,
    allowed_prefix: str,
    output: Path,
    max_files: int,
    max_bytes: int,
    max_concurrency: int,
    content_variant: str = "html",
    force: bool = False,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Mirror a bounded static HTML site and publish it atomically.

    An interrupted run retains a sibling checkpoint directory. Individual
    pages and the checkpoint are atomically written, so resumption never
    trusts a partially downloaded page.
    """

    if content_variant not in {"html", "markdown"}:
        raise ValueError("content_variant must be 'html' or 'markdown'")
    location = _canonical_url(location, allowed_prefix, content_variant) or ""
    if not location:
        raise ValueError("location must be inside allowed_prefix")
    if max_files < 1 or max_bytes < 1 or not 1 <= max_concurrency <= 16:
        raise ValueError("invalid site mirror limits")
    output = output.resolve()
    partial = output.with_name(f".{output.name}.site-partial")
    state_path = partial / "crawl-state.json"
    extracted = partial / "extracted"

    replacing_output = output.exists()
    if replacing_output:
        if _recognized_output(output) and not force:
            return json.loads((output / "site-acquisition-manifest.json").read_text(encoding="utf-8"))
        if not force:
            raise FileExistsError(f"Site mirror output already exists: {output}")
        if not _recognized_output(output):
            raise ValueError(f"Refusing to replace unrecognized output: {output}")
    if force and partial.exists():
        if not state_path.is_file():
            raise ValueError(f"Refusing to replace unrecognized partial output: {partial}")
        shutil.rmtree(partial)

    partial.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("schema_version") != SITE_MIRROR_SCHEMA_VERSION:
            raise ValueError("Site mirror checkpoint schema mismatch")
        if (
            state.get("location") != location
            or state.get("allowed_prefix") != allowed_prefix
            or state.get("content_variant", "html") != content_variant
        ):
            raise ValueError("Site mirror checkpoint configuration mismatch")
        state.setdefault("skipped", {})
    else:
        state = {
            "schema_version": SITE_MIRROR_SCHEMA_VERSION,
            "location": location,
            "allowed_prefix": allowed_prefix,
            "content_variant": content_variant,
            "pending": [location],
            "pages": {},
            "skipped": {},
            "byte_count": 0,
        }
        _atomic_json(state_path, state)

    saved_this_run = 0
    while state["pending"]:
        batch = sorted(set(state["pending"][:max_concurrency]))
        state["pending"] = state["pending"][len(batch) :]
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            fetched = list(
                executor.map(
                    lambda url: _fetch_page(url, allowed_prefix, content_variant=content_variant),
                    batch,
                )
            )
        for page, data in fetched:
            if isinstance(page, SkippedPage):
                state["skipped"][page.url] = {"http_status": page.status}
                continue
            if page.url in state["pages"]:
                continue
            if len(state["pages"]) + 1 > max_files:
                raise RuntimeError(f"Site mirror exceeded max_files={max_files}")
            if state["byte_count"] + page.byte_count > max_bytes:
                raise RuntimeError(f"Site mirror exceeded max_bytes={max_bytes}")
            destination = extracted.joinpath(*Path(page.relative_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            state["pages"][page.url] = {
                "relative_path": page.relative_path,
                "bytes": page.byte_count,
                "sha256": page.sha256,
            }
            state["byte_count"] += page.byte_count
            known = set(state["pages"]) | set(state["skipped"]) | set(state["pending"])
            state["pending"].extend(link for link in page.links if link not in known)
            saved_this_run += 1
        state["pending"] = sorted(set(state["pending"]))
        _atomic_json(state_path, state)
        print(
            f"Mirrored {len(state['pages']):,} pages / {state['byte_count']:,} bytes; "
            f"skipped {len(state['skipped']):,}; queued {len(state['pending']):,}"
        )
        if stop_after is not None and saved_this_run >= stop_after:
            raise InterruptedError("test-requested site mirror interruption")

    inventory = [
        {"url": url, **metadata}
        for url, metadata in sorted(state["pages"].items())
    ]
    aggregate = hashlib.sha256()
    for item in inventory:
        aggregate.update(item["url"].encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(item["sha256"].encode("ascii"))
        aggregate.update(b"\n")
    manifest = {
        "schema_version": SITE_MIRROR_SCHEMA_VERSION,
        "completed": True,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "location": location,
        "allowed_prefix": allowed_prefix,
        "content_variant": content_variant,
        "document_count": len(inventory),
        "byte_count": state["byte_count"],
        "aggregate_sha256": aggregate.hexdigest(),
        "publisher_checksum_verified": False,
        "skipped_count": len(state["skipped"]),
        "skipped": [
            {"url": url, **metadata}
            for url, metadata in sorted(state["skipped"].items())
        ],
        "files": inventory,
    }
    _atomic_json(partial / "site-acquisition-manifest.json", manifest)
    state_path.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    if replacing_output:
        backup = output.with_name(f".{output.name}.{os.getpid()}.previous")
        if backup.exists():
            raise FileExistsError(f"Site mirror replacement backup already exists: {backup}")
        os.replace(output, backup)
        try:
            os.replace(partial, output)
        except BaseException:
            os.replace(backup, output)
            raise
        shutil.rmtree(backup)
    else:
        os.replace(partial, output)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire a bounded, resumable static documentation site mirror")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    matches = [item for item in registry if item.dataset_id == args.dataset]
    if len(matches) != 1:
        raise ValueError(f"Unknown or duplicate dataset ID {args.dataset!r}")
    dataset = matches[0]
    acquisition = dataset.acquisition
    if acquisition.get("method") != "http-site-mirror":
        raise ValueError(f"Dataset {args.dataset!r} is not an HTTP site mirror")
    content_variant = str(acquisition.get("content_variant", "html"))
    location = str(acquisition.get("variant_location", acquisition["location"]))
    allowed_prefix = str(acquisition.get("variant_allowed_prefix", acquisition["allowed_prefix"]))
    manifest = mirror_site(
        location=location,
        allowed_prefix=allowed_prefix,
        output=(args.project_root / dataset.paths["raw"]),
        max_files=int(acquisition["max_files"]),
        max_bytes=int(acquisition["max_bytes"]),
        max_concurrency=int(acquisition["max_concurrency"]),
        content_variant=content_variant,
        force=args.force,
    )
    print(json.dumps({key: manifest[key] for key in ("document_count", "byte_count", "aggregate_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
