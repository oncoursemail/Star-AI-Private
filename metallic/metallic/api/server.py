"""HTTPS server for the API (standard library, same pattern as metallic accounts: TLS wrapped in the handler thread,
15 s idle timeout, 64 KiB body cap, no request logging so tokens never reach a log)."""
from __future__ import annotations

import http.server
import ssl
import threading

MAX_BODY = 65_536
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "X-Frame-Options": "DENY",
           "Strict-Transport-Security": "max-age=31536000"}


def make_handler(api):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "MetallicAPI"
        sys_version = ""
        timeout = 15
        protocol_version = "HTTP/1.1"

        def _serve(self, method: str):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            code, extra, data = api.handle(method, self.path, headers, body, self.client_address[0])
            self.send_response(code)
            for k, v in {**HEADERS, **extra}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_HEAD(self):
            self._serve("HEAD")

        def do_POST(self):
            self._serve("POST")

        def do_PUT(self):
            self._serve("PUT")

        def do_PATCH(self):
            self._serve("PATCH")

        def do_DELETE(self):
            self._serve("DELETE")

        def do_OPTIONS(self):
            self._serve("OPTIONS")

        def log_message(self, fmt, *args):
            return
    return Handler


class _TLSServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    ssl_ctx: ssl.SSLContext | None = None

    def finish_request(self, request, client_address):
        if self.ssl_ctx is not None:
            request.settimeout(10)
            try:
                request = self.ssl_ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError):
                return
        super().finish_request(request, client_address)


def serve(api, host: str, port: int, tls: tuple[str, str] | None = None) -> http.server.ThreadingHTTPServer:
    server = _TLSServer((host, port), make_handler(api))
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(*tls)
        server.ssl_ctx = ctx
    threading.Thread(target=server.serve_forever, daemon=True, name=f"metallic-api-{port}").start()
    return server
