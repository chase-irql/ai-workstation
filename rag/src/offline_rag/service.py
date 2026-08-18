from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .bm25 import QUERY_MODES, search
from .retrieval import index_status, retrieve_document


MAX_REQUEST_BYTES = 64 * 1024
MAX_QUERY_CHARACTERS = 2_000

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Offline Wikipedia</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1020; --panel:#141b2d; --line:#29334c; --text:#edf2ff; --muted:#9da9c4; --accent:#7db3ff; }
    * { box-sizing:border-box; }
    body { margin:0; font:16px/1.5 system-ui,sans-serif; background:radial-gradient(circle at 20% 0,#17284b 0,var(--bg) 38%); color:var(--text); }
    main { width:min(980px,calc(100% - 32px)); margin:0 auto; padding:48px 0 80px; }
    h1 { margin:0; font-size:clamp(2rem,7vw,4rem); letter-spacing:-.055em; }
    .tagline,.meta { color:var(--muted); }
    form { display:grid; grid-template-columns:1fr auto auto; gap:10px; margin:30px 0 16px; }
    input,select,button { border:1px solid var(--line); border-radius:10px; padding:12px 14px; font:inherit; color:var(--text); background:#0f1628; }
    input:focus,select:focus,button:focus { outline:2px solid var(--accent); outline-offset:2px; }
    button { cursor:pointer; background:#245da8; border-color:#397bd0; font-weight:700; }
    button.secondary { background:#18233a; font-weight:600; }
    #status { min-height:26px; margin-bottom:14px; }
    article { background:color-mix(in srgb,var(--panel) 94%,transparent); border:1px solid var(--line); border-radius:14px; padding:18px; margin:12px 0; box-shadow:0 14px 36px #0004; }
    h2 { margin:0 0 5px; font-size:1.2rem; }
    a { color:var(--accent); }
    .heading { color:#c0cbe1; font-size:.9rem; }
    .excerpt { white-space:pre-wrap; margin:12px 0; }
    .citation { color:var(--muted); font-size:.85rem; overflow-wrap:anywhere; }
    .chunks { border-top:1px solid var(--line); margin-top:14px; padding-top:8px; }
    .chunk { padding:10px 0; border-bottom:1px solid #26304a; white-space:pre-wrap; }
    .error { color:#ff9d9d; }
    @media (max-width:650px) { form { grid-template-columns:1fr; } main { padding-top:28px; } }
  </style>
</head>
<body><main>
  <h1>Offline Wikipedia</h1>
  <p class="tagline">Local, source-backed search. No Internet, cloud, model, or GPU required.</p>
  <form id="search-form">
    <input id="query" name="q" maxlength="2000" autofocus required placeholder="Search 19 million Wikipedia articles">
    <select id="mode" aria-label="Query mode"><option value="and">All terms</option><option value="or">Any term</option><option value="phrase">Phrase</option><option value="exact">Exact tokens</option></select>
    <button type="submit">Search</button>
  </form>
  <div id="status" class="meta">Checking local index…</div>
  <section id="results"></section>
</main>
<script>
const form=document.querySelector('#search-form'), query=document.querySelector('#query'), mode=document.querySelector('#mode'), status=document.querySelector('#status'), results=document.querySelector('#results');
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
async function json(url,options){const r=await fetch(url,options);const body=await r.json();if(!r.ok)throw new Error(body.error?.message||`HTTP ${r.status}`);return body}
async function health(){try{const h=await json('/health');status.textContent=`Ready · ${Number(h.index.document_count||0).toLocaleString()} documents · ${Number(h.index.chunk_count||0).toLocaleString()} chunks`;}catch(e){status.className='error';status.textContent=e.message}}
function resultCard(item){
  const card=node('article'), title=node('h2'), link=node('a',null,item.title);link.href=item.source_url||'#';link.target='_blank';link.rel='noreferrer';title.append(link);card.append(title);
  if(item.heading_path?.length)card.append(node('div','heading',item.heading_path.join(' › ')));
  card.append(node('div','excerpt',item.text));card.append(node('div','citation',item.citation));
  const button=node('button','secondary','Read article chunks');button.type='button';button.addEventListener('click',async()=>{button.disabled=true;button.textContent='Loading…';try{const d=await json(`/v1/documents/${encodeURIComponent(item.document_id)}?limit=50`);const box=node('div','chunks');for(const c of d.chunks){const heading=c.heading_path?.length?`${c.heading_path.join(' › ')}\n`:'';box.append(node('div','chunk',heading+c.text))}if(d.pagination.has_more)box.append(node('div','meta',`Showing 50 of ${d.pagination.total_chunks} chunks.`));card.append(box);button.remove()}catch(e){button.disabled=false;button.textContent='Retry article';status.className='error';status.textContent=e.message}});card.append(button);return card;
}
form.addEventListener('submit',async e=>{e.preventDefault();results.replaceChildren();status.className='meta';status.textContent='Searching local index…';try{const data=await json('/v1/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({query:query.value,mode:mode.value,limit:12})});status.textContent=`${data.results.length} results in ${data.latency_ms.toFixed(1)} ms`;for(const item of data.results)results.append(resultCard(item));}catch(err){status.className='error';status.textContent=err.message}});
health();
</script></body></html>"""


class WikipediaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _positive_integer(value: Any, name: str, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= result <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return result


def _search_request(database: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", payload.get("q", ""))).strip()
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"query must not exceed {MAX_QUERY_CHARACTERS} characters")
    mode = str(payload.get("mode", "and"))
    if mode not in QUERY_MODES:
        raise ValueError(f"mode must be one of: {', '.join(QUERY_MODES)}")
    limit = _positive_integer(payload.get("limit", 8), "limit", 50)
    started = time.perf_counter()
    candidate_limit = min(500, max(limit, limit * 10))
    candidates = search(database, query, limit=candidate_limit, mode=mode)
    results: list[dict[str, object]] = []
    seen_documents: set[str] = set()
    for candidate in candidates:
        document_id = str(candidate["document_id"])
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        results.append(candidate)
        if len(results) == limit:
            break
    return {
        "query": query,
        "mode": mode,
        "limit": limit,
        "ranking_unit": "document",
        "candidate_chunks": len(candidates),
        "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
        "results": results,
    }


def make_handler(database: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OfflineWikipedia/0.3"

        def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _error(self, status: int, code: str, message: str) -> None:
            self._send_json(status, {"error": {"code": code, "message": message}})

        def _payload(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length < 1 or length > MAX_REQUEST_BYTES:
                raise ValueError(f"request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
            try:
                value = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as error:
                raise ValueError("request body must be valid JSON") from error
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._send_bytes(HTTPStatus.OK, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if parsed.path == "/favicon.ico":
                    self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                    return
                if parsed.path in {"/health", "/v1/status"}:
                    self._send_json(HTTPStatus.OK, {"status": "ok", "index": index_status(database)})
                    return
                if parsed.path == "/v1/search":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    payload = {key: values[-1] for key, values in query.items()}
                    self._send_json(HTTPStatus.OK, _search_request(database, payload))
                    return
                prefix = "/v1/documents/"
                if parsed.path.startswith(prefix):
                    document_id = unquote(parsed.path[len(prefix) :])
                    query = parse_qs(parsed.query)
                    offset = int(query.get("offset", ["0"])[-1])
                    limit = _positive_integer(query.get("limit", ["20"])[-1], "limit", 200)
                    self._send_json(
                        HTTPStatus.OK,
                        retrieve_document(database, document_id, chunk_offset=offset, chunk_limit=limit),
                    )
                    return
                self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            except KeyError as error:
                self._error(HTTPStatus.NOT_FOUND, "document_not_found", str(error.args[0]))
            except (TypeError, ValueError) as error:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))
            except FileNotFoundError as error:
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "index_unavailable", str(error))

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            try:
                if urlparse(self.path).path != "/v1/search":
                    self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
                    return
                self._send_json(HTTPStatus.OK, _search_request(database, self._payload()))
            except (TypeError, ValueError) as error:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))
            except FileNotFoundError as error:
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "index_unavailable", str(error))

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

    return Handler


def create_server(database: Path, host: str = "127.0.0.1", port: int = 8765) -> WikipediaHTTPServer:
    """Create a read-only local Wikipedia HTTP server."""

    index_status(database)
    if not 0 <= port <= 65_535:
        raise ValueError("port must be between 0 and 65535")
    return WikipediaHTTPServer((host, port), make_handler(database.resolve()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the offline Wikipedia index over local HTTP.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(args.database, args.host, args.port)
    host, port = server.server_address[:2]
    print(json.dumps({"status": "ready", "url": f"http://{host}:{port}", "database": str(args.database.resolve())}))
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
