"""Webhook receiver (standard library): verify, answer 204 fast, de-duplicate on the event id."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from metallic_api import verify_webhook

SECRET = os.environ["METALLIC_WEBHOOK_SECRET"]
seen: set[str] = set()


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not verify_webhook(SECRET, self.headers.get("Metallic-Signature", ""), raw):
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()
        event = json.loads(raw)
        if event["id"] not in seen:
            seen.add(event["id"])
            print(event["type"], event["data"])


HTTPServer(("127.0.0.1", 8787), Hook).serve_forever()
