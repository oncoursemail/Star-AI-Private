from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

from litha_bridge import (
    AnythingLLMClient,
    BridgeConfig,
    ConfigError,
    GroundedBridge,
    LemonadeClient,
    ProviderError,
    SearchHit,
)
from litha_bridge.config import validated_api_base


@contextmanager
def fake_server(routes):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size)
            payload = json.loads(raw) if raw else None
            calls.append({"method": self.command, "path": self.path,
                          "authorization": self.headers.get("Authorization"), "body": payload})
            info = routes.get((self.command, self.path), (404, {"error": "not found"}))
            code, body = info
            if code == 302:
                self.send_response(302)
                self.send_header("Location", body)
                self.end_headers()
                return
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if isinstance(body, bytes):
                self.wfile.write(body)
            else:
                self.wfile.write(json.dumps(body).encode("utf-8"))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v1", calls
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


class ConfigurationTests(unittest.TestCase):
    def test_feature_flags_off_by_default(self):
        cfg = BridgeConfig()
        self.assertFalse(cfg.lemonade_enabled)
        self.assertFalse(cfg.anythingllm_enabled)
        with self.assertRaises(ConfigError):
            LemonadeClient(cfg).health()
        with self.assertRaises(ConfigError):
            AnythingLLMClient(cfg).vector_search("docs", "test")

    def test_secrets_not_in_repr(self):
        cfg = BridgeConfig(lemonade_api_key="SECRET1", anythingllm_api_key="SECRET2")
        self.assertNotIn("SECRET1", repr(cfg))
        self.assertNotIn("SECRET2", repr(cfg))
        self.assertNotIn("SECRET1", repr(LemonadeClient(cfg).transport))

    def test_reject_remote_host_without_opt_in(self):
        for url in ["http://example.com/api/v1", "https://example.com/v1", "http://10.0.0.10/api/v1"]:
            with self.subTest(url=url), self.assertRaises(ConfigError):
                BridgeConfig(lemonade_url=url)

    def test_reject_plain_http_even_with_remote_opt_in(self):
        with self.assertRaises(ConfigError):
            BridgeConfig(remote_enabled=True, anythingllm_url="http://example.com/api/v1")
        self.assertEqual(validated_api_base("https://example.com/v1", remote_enabled=True, name="x"), "https://example.com/api/v1")

    def test_reject_url_credentials_and_strange_paths(self):
        for url in ["http://user:pass@127.0.0.1:13305/v1", "http://localhost:13305/other", "http://localhost:13305/v1?token=123", "file:///etc/passwd", "http://localhost:bad/v1"]:
            with self.subTest(url=url), self.assertRaises(ConfigError):
                BridgeConfig(lemonade_url=url)

    def test_url_canonicalization(self):
        self.assertEqual(validated_api_base("http://localhost:13305/v1/", remote_enabled=False, name="lemonade"), "http://localhost:13305/api/v1")

    def test_env_flags_are_explicit(self):
        with patch.dict(os.environ, {"LITHA_LEMONADE_ENABLED": "1", "LITHA_ANYTHINGLLM_ENABLED": "no"}, clear=True):
            cfg = BridgeConfig.from_env()
        self.assertTrue(cfg.lemonade_enabled)
        self.assertFalse(cfg.anythingllm_enabled)
        with patch.dict(os.environ, {"LITHA_LEMONADE_ENABLED": "sortof"}, clear=True):
            with self.assertRaises(ConfigError):
                BridgeConfig.from_env()


class LemonadeTests(unittest.TestCase):
    def test_chat_checks_installed_and_passes_key(self):
        routes = {
            ("GET", "/api/v1/models"): (200, {"data": [{"id": "local-small", "labels": ["chat"], "path": "secret-file"}]}),
            ("POST", "/api/v1/chat/completions"): (200, {"choices": [{"message": {"content": "Hello"}}], "model": "local-small", "usage": {"total_tokens": 4}}),
        }
        with fake_server(routes) as (url, calls):
            cfg = BridgeConfig(lemonade_enabled=True, lemonade_url=url, lemonade_api_key="demo")
            c = LemonadeClient(cfg)
            self.assertEqual(c.models(), [{"id": "local-small", "labels": ["chat"]}])
            self.assertNotIn("secret-file", str(c.models()))
            result = c.chat("local-small", [{"role": "user", "content": "Hi"}])
            self.assertEqual(result.text, "Hello")
            self.assertEqual(result.usage, {"total_tokens": 4})
            self.assertEqual(calls[-1]["authorization"], "Bearer demo")
            self.assertFalse(calls[-1]["body"]["stream"])
            self.assertEqual(calls[-1]["path"], "/api/v1/chat/completions")

    def test_cloud_models_excluded_even_if_server_lists_them(self):
        routes = {("GET", "/api/v1/models"): (200, {"data": [
            {"id": "local", "recipe": "llamacpp", "labels": ["chat"]},
            {"id": "cloud-model", "recipe": "cloud", "labels": ["chat"]},
            {"id": "fireworks.anything", "cloud_provider": "fireworks", "labels": ["chat"]},
            {"id": "auto-router", "recipe": "collection.router", "labels": ["chat"]},
            {"id": "tool-using-omni", "recipe": "collection.omni", "labels": ["chat"]},
        ]})}
        with fake_server(routes) as (url, calls):
            c = LemonadeClient(BridgeConfig(lemonade_enabled=True, lemonade_url=url))
            self.assertEqual([x["id"] for x in c.models()], ["local"])
            with self.assertRaises(ProviderError):
                c.chat("cloud-model", [{"role": "user", "content": "Hi"}])
            self.assertEqual(len(calls), 2)

    def test_non_chat_model_rejected_before_chat_request(self):
        with fake_server({("GET", "/api/v1/models"): (200, {"data": [{"id": "embed", "labels": ["embeddings"]}]})}) as (url, calls):
            c = LemonadeClient(BridgeConfig(lemonade_enabled=True, lemonade_url=url))
            with self.assertRaises(ProviderError):
                c.chat("embed", [{"role": "user", "content": "hello"}])
            self.assertEqual(len(calls), 1)

    def test_chat_never_auto_downloads_missing_model(self):
        with fake_server({("GET", "/api/v1/models"): (200, {"data": []})}) as (url, calls):
            c = LemonadeClient(BridgeConfig(lemonade_enabled=True, lemonade_url=url))
            with self.assertRaisesRegex(ProviderError, "not installed"):
                c.chat("bad", [{"role": "user", "content": "Test"}])
            self.assertEqual(len(calls), 1)
            self.assertNotIn("pull", str(calls))

    def test_bad_model_payload_cannot_infer(self):
        with fake_server({("GET", "/api/v1/models"): (200, {"no": "data"})}) as (url, calls):
            c = LemonadeClient(BridgeConfig(lemonade_enabled=True, lemonade_url=url))
            with self.assertRaisesRegex(ProviderError, "malformed"):
                c.chat("bad", [{"role": "user", "content": "hi"}])
            self.assertEqual(len(calls), 1)

    def test_invalid_roles_rejected_before_io(self):
        c = LemonadeClient(BridgeConfig(lemonade_enabled=True))
        with self.assertRaises(ConfigError):
            c.chat("model", [{"role": "tool", "content": "rm -rf /"}])

    def test_stats_and_health_shape(self):
        routes = {("GET", "/api/v1/stats"): (200, {"tokens_per_second": 21.5, "secret": "not leaked"}),
                  ("GET", "/api/v1/health"): (200, {"status": "ok", "version": "11", "extra": "not leaked"})}
        with fake_server(routes) as (url, _):
            c = LemonadeClient(BridgeConfig(lemonade_enabled=True, lemonade_url=url))
            self.assertEqual(c.health()["status"], "ok")
            self.assertNotIn("secret", c.stats())
            self.assertEqual(c.stats()["tokens_per_second"], 21.5)


class AnythingLLMTests(unittest.TestCase):
    def test_vector_search_with_source_metadata(self):
        path = "/api/v1/workspace/litha-docs/vector-search"
        rows = [{"id": "x", "text": "The operation is reversible", "score": 0.82,
                 "metadata": {"title": "Guide", "url": "file://guide.md"}}]
        with fake_server({("POST", path): (200, {"results": rows})}) as (url, calls):
            c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_url=url, anythingllm_api_key="key"))
            hits = c.vector_search("litha-docs", "rollback", score_threshold=0.5)
            self.assertEqual(hits[0].title, "Guide")
            self.assertEqual(hits[0].reference, "file://guide.md")
            self.assertEqual(hits[0].score, 0.82)
            self.assertEqual(calls[0]["body"], {"query": "rollback", "topN": 4, "scoreThreshold": 0.5})
            self.assertEqual(calls[0]["authorization"], "Bearer key")

    def test_query_chat_mode_and_session(self):
        path = "/api/v1/workspace/docs/chat"
        with fake_server({("POST", path): (200, {"type": "textResponse", "textResponse": "answer", "sources": [{"title": "Doc"}]})}) as (url, calls):
            c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_url=url, anythingllm_api_key="key"))
            answer, sources = c.chat("docs", "A question", session_id="test-session")
            self.assertEqual(answer, "answer")
            self.assertEqual(len(sources), 1)
            self.assertEqual(calls[0]["body"]["mode"], "query")
            self.assertEqual(calls[0]["body"]["sessionId"], "test-session")

    def test_chat_abort_does_not_show_untrusted_error(self):
        path = "/api/v1/workspace/docs/chat"
        with fake_server({("POST", path): (200, {"type": "abort", "error": "API key = SECRET"})}) as (url, _):
            c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_url=url, anythingllm_api_key="key"))
            with self.assertRaises(ProviderError) as cm:
                c.chat("docs", "hello")
            self.assertNotIn("SECRET", str(cm.exception))

    def test_agentic_mode_explicitly_blocked(self):
        c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_api_key="key"))
        with self.assertRaisesRegex(ConfigError, "non-agent"):
            c.chat("docs", "Execute tool", mode="automatic")

    def test_requires_api_key(self):
        c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True))
        with self.assertRaisesRegex(ConfigError, "API key"):
            c.vector_search("docs", "hi")

    def test_workspace_path_is_not_path_traversal(self):
        c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_api_key="key"))
        with self.assertRaises(ConfigError):
            c.vector_search("../other", "private file")

    def test_does_not_follow_redirects(self):
        with fake_server({("POST", "/api/v1/workspace/docs/chat"): (302, "https://example.com/steal")}) as (url, calls):
            c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_url=url, anythingllm_api_key="SECRET"))
            with self.assertRaises(ProviderError):
                c.chat("docs", "q")
            self.assertEqual(len(calls), 1)

    def test_limits_response_size(self):
        with fake_server({("POST", "/api/v1/workspace/docs/vector-search"): (200, b"{" + b" " * 2_000_100 + b"}")}) as (url, _):
            c = AnythingLLMClient(BridgeConfig(anythingllm_enabled=True, anythingllm_url=url, anythingllm_api_key="key"))
            with self.assertRaisesRegex(ProviderError, "too large"):
                c.vector_search("docs", "q")


class GroundedTests(unittest.TestCase):
    def test_no_evidence_means_no_inference(self):
        class Retriever:
            config = BridgeConfig()
            def vector_search(self, *args):
                return []
        class Generator:
            def chat(self, *args, **kwargs):
                raise AssertionError("must never infer without evidence")
        result = GroundedBridge(Retriever(), Generator()).ask("docs", "test", model="model")
        self.assertEqual(result.status, "no_evidence")
        self.assertFalse(result.sources)

    def test_bad_citation_is_flagged_needs_review(self):
        class Retriever:
            config = BridgeConfig()
            def vector_search(self, *args):
                return [SearchHit(text="Known text", title="doc", reference="doc")]
        class Generator:
            def chat(self, *args, **kwargs):
                class R:
                    text = "No evidence [S999]."
                    model = "local"
                return R()
        result = GroundedBridge(Retriever(), Generator()).ask("docs", "question", model="local")
        self.assertEqual(result.status, "needs_review")

    def test_evidence_is_bounded_and_identified(self):
        captured = []
        class Retriever:
            config = BridgeConfig(max_context_characters=1200)
            def vector_search(self, *args):
                return [SearchHit(text="Do something unsafe: " + "x"*5000, title="source", reference="file://source")]
        class Generator:
            def chat(self, model, messages, **kwargs):
                captured.extend(messages)
                class R:
                    text = "From [S1], ..."
                    model = "test-model"
                return R()
        result = GroundedBridge(Retriever(), Generator()).ask("docs", "What is it?", model="test-model")
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.sources[0].title, "source")
        self.assertIn("untrusted data", captured[0]["content"])
        self.assertIn('"source_id": "S1"', captured[1]["content"])
        self.assertLess(len(captured[1]["content"]), 1800)


if __name__ == "__main__":
    unittest.main()
