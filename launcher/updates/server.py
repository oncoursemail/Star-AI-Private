"""A small static file server for a release folder: GET/HEAD, single-range requests (so downloads resume), no listing.

Use it to try the update channel on one PC (`python -m launcher.updates serve --dir out --port 8099`), and from tests,
where `faults` lets a test tamper with, truncate or drop a given path. For real hosting put the same folder behind any
web server (see metallic-site/HOSTING.md); nothing here needs to run in production.
"""
from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

_RANGE = re.compile(r"^bytes=(\d+)-(\d*)$")


def make_handler(root: Path, faults: dict | None = None, log: list | None = None):
    root = Path(root).resolve()
    faults = faults if faults is not None else {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet
            pass

        def _target(self) -> Path | None:
            rel = unquote(urlsplit(self.path).path).lstrip("/")
            p = (root / rel).resolve()
            return p if root in p.parents and p.is_file() else None

        def _serve(self, head: bool) -> None:
            rel = unquote(urlsplit(self.path).path).lstrip("/")
            if log is not None:
                log.append((self.command, rel, self.headers.get("Range")))
            fault = faults.get(rel)
            p = self._target()
            if p is None or fault == "404":
                self.send_error(404)
                return
            data = p.read_bytes()
            if callable(fault):
                data = fault(data)
            start, end, status = 0, len(data) - 1, 200
            m = _RANGE.match(self.headers.get("Range", ""))
            if m:
                start = int(m[1])
                if start >= len(data):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(data)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(int(m[2]) if m[2] else len(data) - 1, len(data) - 1)
                status = 206
            body = data[start:end + 1]
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream" if "blobs" in rel else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store" if rel.endswith((".json", ".sig")) else "public, max-age=31536000, immutable")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.end_headers()
            if head:
                return
            if fault == "drop-half" and not start:  # send half the body, then cut the connection
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                self.close_connection = True
                return
            self.wfile.write(body)

        def do_GET(self):
            self._serve(False)

        def do_HEAD(self):
            self._serve(True)

    return Handler


def start(root: Path, port: int = 0, bind: str = "127.0.0.1", faults: dict | None = None, log: list | None = None):
    """Start the server in a background thread. Returns (server, base_url). Call server.shutdown() when done."""
    server = ThreadingHTTPServer((bind, port), make_handler(root, faults, log))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{bind}:{server.server_address[1]}/"
