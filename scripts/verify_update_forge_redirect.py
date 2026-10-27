"""Exercise the real urllib redirect pipeline with fake transports and synthetic publishing data only."""
from __future__ import annotations

from contextlib import contextmanager
from email.message import Message
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launcher.updates import forge  # noqa: E402
from launcher.updates.sources import HttpSource  # noqa: E402

ORIGIN = "https://forge.example.invalid"
TOKEN = "synthetic-verifier-token"
REAL_BUILD_OPENER = urllib.request.build_opener


class Reply(io.BytesIO):
    def __init__(self, url, code, body, headers):
        super().__init__(body)
        self.url, self.code, self.status, self.msg = url, code, code, "Synthetic response"
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name] = value

    def info(self):
        return self.headers

    def geturl(self):
        return self.url


class Transport(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def __init__(self, respond):
        super().__init__()
        self.respond = respond
        self.requests = []
        self.replies = []

    def http_open(self, request):
        self.requests.append(request)
        code, body, headers = self.respond(request)
        response = Reply(request.full_url, code, body, headers)
        self.replies.append(response)
        return response

    def https_open(self, req):
        return self.http_open(req)


@contextmanager
def transport_for(respond):
    transport = Transport(respond)

    def opener(*handlers):
        # Real redirect/error processors; both real HTTP transports are replaced.
        return REAL_BUILD_OPENER(urllib.request.ProxyHandler({}), *handlers, transport)

    with (patch("urllib.request.build_opener", side_effect=opener),
          patch("socket.create_connection", side_effect=AssertionError("Network forbidden")),
          patch("urllib.request.install_opener", side_effect=AssertionError("Global opener mutation forbidden"))):
        try:
            yield transport
        finally:
            for reply in transport.replies:
                reply.close()


class ForgeRedirectChecks(unittest.TestCase):
    def test_all_authenticated_redirects_stop_before_a_second_dispatch(self):
        for method in ("GET", "POST", "DELETE"):
            for code in (301, 302, 303, 307, 308):
                for destination in (ORIGIN + "/canonical", "https://foreign.example.invalid/steal",
                                    "http://forge.example.invalid/downgrade"):
                    with self.subTest(method=method, code=code, destination=destination):
                        def respond(_request, code=code, destination=destination):
                            return code, b"", {"Location": destination}

                        with transport_for(respond) as transport:
                            with self.assertRaises(forge.ForgeError) as caught:
                                forge._call(method, ORIGIN + "/api/v1/releases", TOKEN,
                                            b"{}" if method == "POST" else None)
                            self.assertEqual(len(transport.requests), 1)
                            request = transport.requests[0]
                            self.assertEqual(request.full_url, ORIGIN + "/api/v1/releases")
                            self.assertEqual(request.get_header("Authorization"), "token " + TOKEN)
                            self.assertEqual(request.get_method(), method)
                            self.assertNotIn(TOKEN, str(caught.exception))

    def test_normal_json_request_preserves_method_headers_body_timeout_and_closure(self):
        with transport_for(lambda _r: (200, b'{"id": 17}', {})) as transport:
            body = b'{"tag_name":"synthetic"}'
            result = forge._call("POST", ORIGIN + "/api/v1/releases", TOKEN, body,
                                 {"Content-Type": "application/json", "X-Request-Id": "synthetic"})
            self.assertEqual(result, {"id": 17})
            request = transport.requests[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.data, body)
            self.assertEqual(request.get_header("Authorization"), "token " + TOKEN)
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertEqual(request.get_header("X-request-id"), "synthetic")
            self.assertEqual(request.timeout, 120)
            self.assertTrue(transport.replies[0].closed)

    def test_empty_json_failure_and_http_error_contracts_are_preserved(self):
        for method, code, body, expected in (("DELETE", 204, b"", None), ("GET", 404, b"", None),
                                             ("GET", 200, b"[]", [])):
            with self.subTest(method=method, code=code):
                with transport_for(lambda _r, code=code, body=body: (code, body, {})):
                    self.assertEqual(forge._call(method, ORIGIN + "/api/v1/releases", TOKEN), expected)
        for method, code in (("POST", 404), ("DELETE", 403), ("GET", 500)):
            with self.subTest(method=method, code=code):
                with transport_for(lambda _r, code=code: (code, b"", {})):
                    with self.assertRaises(forge.ForgeError) as caught:
                        forge._call(method, ORIGIN + "/api/v1/releases", TOKEN)
                    self.assertIn(str(code), str(caught.exception))
                    self.assertNotIn(TOKEN, str(caught.exception))
        with transport_for(lambda _r: (200, b"not-json", {})) as transport:
            with self.assertRaises(json.JSONDecodeError):
                forge._call("GET", ORIGIN + "/api/v1/releases", TOKEN)
            self.assertTrue(transport.replies[0].closed)
        with transport_for(lambda _r: (_ for _ in ()).throw(urllib.error.URLError("synthetic offline"))):
            with self.assertRaisesRegex(forge.ForgeError, "forge unreachable"):
                forge._call("GET", ORIGIN + "/api/v1/releases", TOKEN)

    def test_mock_publishing_roundtrip_retains_create_skip_and_replace_contract(self):
        state = {"created": False, "assets": {}, "next_id": 1}

        def respond(request):
            parsed = urllib.parse.urlsplit(request.full_url)
            method = request.get_method()
            if method == "GET":
                if not state["created"]:
                    return 404, b"", {}
                assets = [{"name": name, "id": ident} for name, ident in state["assets"].items()]
                return 200, json.dumps({"id": 9, "assets": assets}).encode(), {}
            if method == "POST" and parsed.path.endswith("/releases"):
                self.assertTrue(json.loads(request.data)["prerelease"])
                state["created"] = True
                return 200, b'{"id":9,"assets":[]}', {}
            if method == "DELETE":
                ident = int(parsed.path.rsplit("/", 1)[1])
                state["assets"] = {n: i for n, i in state["assets"].items() if i != ident}
                return 204, b"", {}
            self.assertEqual(method, "POST")
            self.assertIn("multipart/form-data", request.get_header("Content-type"))
            name = urllib.parse.parse_qs(parsed.query)["name"][0]
            self.assertIn(('filename="' + name + '"').encode(), request.data)
            state["assets"][name] = state["next_id"]
            state["next_id"] += 1
            return 200, b'{"ok":true}', {}

        with tempfile.TemporaryDirectory(prefix="metallic-forge-contract-") as temp:
            folder = Path(temp)
            (folder / "stable.json").write_bytes(b"synthetic metadata")
            (folder / "synthetic-blob").write_bytes(b"synthetic blob")
            with transport_for(respond) as transport, patch.object(Path, "read_text", return_value=TOKEN) as token_read:
                first = forge.upload_release(ORIGIN, folder / "unused-token-path", "owner/repo", "channel-stable",
                                             folder, prerelease=True)
                second = forge.upload_release(ORIGIN, folder / "unused-token-path", "owner/repo", "channel-stable",
                                              folder, prerelease=True)
                self.assertEqual(token_read.call_count, 2)
                self.assertEqual(first, {"uploaded": ["stable.json", "synthetic-blob"], "skipped": 0})
                self.assertEqual(second, {"uploaded": ["stable.json"], "skipped": 1})
                self.assertTrue(all(r.get_header("Authorization") == "token " + TOKEN for r in transport.requests))
                self.assertEqual(sum(r.get_method() == "DELETE" for r in transport.requests), 1)

    def test_anonymous_blob_source_keeps_its_default_redirect_behavior(self):
        def respond(request):
            if request.full_url.startswith(ORIGIN):
                return 302, b"", {"Location": "https://cdn.example.invalid/blob"}
            return 200, b"synthetic blob", {}

        transport = Transport(respond)
        ordinary = REAL_BUILD_OPENER(urllib.request.ProxyHandler({}), transport)
        with (patch("urllib.request.urlopen", side_effect=lambda req, timeout: ordinary.open(req, timeout=timeout)),
              patch("socket.create_connection", side_effect=AssertionError("Network forbidden"))):
            self.assertEqual(HttpSource(ORIGIN).read("blobs/synthetic"), b"synthetic blob")
        self.assertEqual(len(transport.requests), 2)
        self.assertTrue(all(not r.has_header("Authorization") for r in transport.requests))


if __name__ == "__main__":
    unittest.main(verbosity=2)
