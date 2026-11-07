"""STAR Server (LAN) provider: private-address validation, keyring-only key, probe.

No test here opens a real network connection or touches the real OS keyring:
HTTP goes through httpx.MockTransport and the keyring module is replaced.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, fields
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from star import model_health, providers
from star.brain_router import select_route
from star.desktop_core import Settings, model_context_char_budget
from star.model_health import (SERVER_FAILURES, explain_model_failure, missing_model_message,
                               probe_chat_endpoint, probe_server, server_status)
from star.providers import (ALL_PROVIDERS, KEY_ENV, PROVIDERS, STAR_SERVER, call_limits,
                            connection_for, credential_status, get_api_key, open_client,
                            provider_catalog, provider_kind, provider_spec, save_api_key,
                            validate_lan_endpoint)

LAN = "http://192.168.50.20:8080/v1"
SECRET = "sk-star-server-TEST-0123456789abcdef"


class FakeKeyring:
    """In-memory stand-in so tests never read or write Windows Credential Manager."""
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
    def get_password(self, service, name):
        return self.store.get((service, name))
    def set_password(self, service, name, value):
        self.store[(service, name)] = value
    def delete_password(self, service, name):
        self.store.pop((service, name), None)


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    for variable in KEY_ENV.values():
        monkeypatch.delenv(variable, raising=False)
    providers._SERVER_LIMITS.clear()        # process-memory caches must not leak between tests
    model_health._LAST_SERVER_CHECK.clear()
    return fake


def server_settings(**changes) -> Settings:
    return Settings(**{"provider": "star_server", "server_endpoint": LAN, "model": "star-fast", **changes})


# ---------------------------------------------------------------- provider metadata

def test_star_server_is_a_typed_private_lan_provider():
    spec = provider_spec("star_server")
    assert spec.label == "STAR Server (LAN)" and spec.kind == "lan"
    assert spec.base_url == "" and spec.base_url_from_settings and spec.requires_key
    assert spec.env_var == "STAR_SERVER_API_KEY" and KEY_ENV["star_server"] == "STAR_SERVER_API_KEY"
    assert provider_spec("local").kind == "local" and not provider_spec("local").requires_key
    assert all(p.kind == "cloud" and p.base_url.startswith("https://") for p in PROVIDERS.values())
    assert "star_server" not in PROVIDERS  # never listed with the cloud vendors
    assert set(ALL_PROVIDERS) == {"local", "star_server", *PROVIDERS}
    assert "local" not in KEY_ENV  # the on-device brain has no key


def test_provider_kind_replaces_string_comparisons():
    assert provider_kind(SimpleNamespace(provider="local")) == "local"
    assert provider_kind(SimpleNamespace(provider="star_server")) == "lan"
    assert provider_kind(SimpleNamespace(provider="groq")) == "cloud"
    assert provider_kind(SimpleNamespace()) == "local"  # legacy settings objects
    for unknown in ("custom", "", None, 7, ["local"]):
        with pytest.raises(ValueError):
            provider_kind(SimpleNamespace(provider=unknown))


def test_uses_star_server_never_raises():
    assert providers.uses_star_server(SimpleNamespace(provider="star_server")) is True
    for other in ("local", "groq", "mystery", "", None, 3):
        assert providers.uses_star_server(SimpleNamespace(provider=other)) is False
    assert providers.uses_star_server(SimpleNamespace()) is False


def test_catalog_lists_server_without_any_address_or_key(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    catalog = provider_catalog()
    entry = next(item for item in catalog if item["id"] == "star_server")
    assert entry == {"id": "star_server", "label": "STAR Server (LAN)", "model": "",
                     "connected": True, "kind": "lan"}
    assert SECRET not in json.dumps(catalog)


# ---------------------------------------------------------------- LAN address validation

@pytest.mark.parametrize("good,canonical", [
    ("http://10.20.30.40:8080/v1", "http://10.20.30.40:8080/v1"),
    ("http://10.0.0.1:1024/v1", "http://10.0.0.1:1024/v1"),
    ("http://172.16.0.9:65535/v1", "http://172.16.0.9:65535/v1"),
    ("http://172.31.255.254:8080/v1", "http://172.31.255.254:8080/v1"),
    ("http://192.168.1.20:8080/v1/", "http://192.168.1.20:8080/v1"),
    ("https://192.168.1.20:8443/v1", "https://192.168.1.20:8443/v1"),
    ("http://127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1"),
    ("http://[fd12:3456:789a::1]:8080/v1", "http://[fd12:3456:789a::1]:8080/v1"),
    ("http://[::1]:8080/v1", "http://[::1]:8080/v1"),
])
def test_private_ip_literals_are_accepted(good, canonical):
    assert validate_lan_endpoint(good) == canonical


@pytest.mark.parametrize("bad", [
    "", " ", None, 8080, b"http://10.0.0.1:8080/v1",
    # public or non-private addresses
    "http://8.8.8.8:8080/v1", "http://1.1.1.1:8080/v1", "http://172.32.0.1:8080/v1",
    "http://172.15.255.255:8080/v1", "http://192.169.0.1:8080/v1", "http://11.0.0.1:8080/v1",
    "http://169.254.10.20:8080/v1", "http://169.254.169.254:8080/v1",
    "http://100.64.0.1:8080/v1", "http://192.0.2.10:8080/v1", "http://203.0.113.5:8080/v1",
    "http://0.0.0.0:8080/v1", "http://255.255.255.255:8080/v1", "http://240.0.0.1:8080/v1",
    "http://224.0.0.1:8080/v1", "http://[2001:4860:4860::8888]:8080/v1",
    "http://[::ffff:8.8.8.8]:8080/v1", "http://[::ffff:10.0.0.1]:8080/v1", "http://[::]:8080/v1",  # star:allow placeholder
    "http://[fe80::1]:8080/v1", "http://[fd00:ec2::254]:8080/v1",
    # DNS names may rebind and are not safe without connection-level IP pinning
    "http://localhost:8080/v1", "http://star-server:8080/v1", "http://server.local:8080/v1",
    "http://evil.example:8080/v1", "http://10.0.0.1.evil.example:8080/v1",
    "http://192.168.1.20.nip.io:8080/v1",
    # alternative encodings of an address
    "http://167772161:8080/v1", "http://0x0a000001:8080/v1", "http://010.0.0.1:8080/v1",
    "http://10.1:8080/v1", "http://10.0.0.01:8080/v1", "http://%31%30.0.0.1:8080/v1",
    # credentials, query, fragment
    "http://user:pw@10.0.0.1:8080/v1", "http://token@10.0.0.1:8080/v1",
    "http://10.0.0.1:8080/v1?key=x", "http://10.0.0.1:8080/v1?", "http://10.0.0.1:8080/v1#x",
    "http://10.0.0.1:8080/v1#", "http://8.8.8.8#@10.0.0.1:8080/v1", "http://10.0.0.1:8080@8.8.8.8/v1",
    # port: required, unprivileged, in range
    "http://10.0.0.1/v1", "http://10.0.0.1:80/v1", "https://10.0.0.1:443/v1",
    "http://10.0.0.1:1023/v1", "http://10.0.0.1:0/v1", "http://10.0.0.1:65536/v1",
    "http://10.0.0.1:99999/v1", "http://10.0.0.1:08080/v1", "http://10.0.0.1:abc/v1",
    "http://10.0.0.1:/v1", "http://10.0.0.1:-1/v1",
    # path must be exactly /v1
    "http://10.0.0.1:8080", "http://10.0.0.1:8080/", "http://10.0.0.1:8080/v2",
    "http://10.0.0.1:8080/api/v1", "http://10.0.0.1:8080/v1/chat", "http://10.0.0.1:8080/v1//",
    "http://10.0.0.1:8080/v1/../admin", "http://10.0.0.1:8080/V1", "http://10.0.0.1:8080/v1;x",
    # scheme and shape
    "ftp://10.0.0.1:8080/v1", "file:///etc/passwd", "ws://10.0.0.1:8080/v1", "10.0.0.1:8080/v1",
    "//10.0.0.1:8080/v1", "HTTP://10.0.0.1:8080/v1", "http:/10.0.0.1:8080/v1",
    "http://10.0.0.1:8080\\v1", "http://10.0.0.1:8080/v1 ", " http://10.0.0.1:8080/v1",
    "http://10.0.0.1:8080/v1\n", "http://10.0.\t0.1:8080/v1", "http://10.0.0.1:8080/v1\x00",
    "http://[fe80::1%25eth0]:8080/v1", "http://[fd12::1:8080/v1", "http://" + "1" * 300 + ":8080/v1",
])
def test_everything_else_is_refused(bad):
    with pytest.raises(ValueError):
        validate_lan_endpoint(bad)


def test_lan_address_is_accepted_only_in_the_server_field():
    # The loopback rule for `endpoint` is untouched: a LAN address there still fails.
    with pytest.raises(ValueError, match="loopback"):
        Settings(endpoint="http://10.20.30.40:8080/v1").validate()
    with pytest.raises(ValueError, match="loopback"):
        Settings(endpoint=LAN, provider="star_server", server_endpoint=LAN).validate()
    Settings(server_endpoint="http://10.20.30.40:8080/v1").validate()
    server_settings().validate()
    # A bad server address is refused even while another provider is selected.
    for bad in ("http://8.8.8.8:8080/v1", "http://star.example:8080/v1", "http://0.0.0.0:8080/v1",
                "http://u:p@10.0.0.1:8080/v1", "http://10.0.0.1:8080/v1?x=1", ["http://10.0.0.1:8080/v1"]):
        with pytest.raises(ValueError):
            Settings(server_endpoint=bad).validate()


def test_server_provider_needs_an_address_and_has_no_built_in_one():
    defaults = Settings()
    assert defaults.server_endpoint == "" and defaults.provider == "local"
    assert (defaults.server_timeout, defaults.server_parallel, defaults.server_context_tokens) == (600, 1, 0)
    with pytest.raises(ValueError, match="Enter your STAR Server address"):
        Settings(provider="star_server").validate()


@pytest.mark.parametrize("field,bad", [
    ("server_timeout", 29), ("server_timeout", 1801), ("server_timeout", 60.0), ("server_timeout", "600"),
    ("server_timeout", True), ("server_timeout", None),
    ("server_parallel", 0), ("server_parallel", 5), ("server_parallel", 1.0), ("server_parallel", True),
    ("server_context_tokens", -1), ("server_context_tokens", 512), ("server_context_tokens", 2_000_000),
    ("server_context_tokens", "32768"), ("server_context_tokens", None),
])
def test_server_number_settings_are_bounded(field, bad):
    with pytest.raises(ValueError):
        server_settings(**{field: bad}).validate()


def test_server_settings_round_trip_and_old_files_still_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"provider":"local","model":"qwen","project":"STAR"}', encoding="utf-8")
    old = Settings.load(path)
    assert old.server_endpoint == "" and old.server_timeout == 600
    saved = server_settings(server_timeout=900, server_parallel=2, server_context_tokens=32768)
    saved.save(path)
    again = Settings.load(path)
    assert (again.provider, again.server_endpoint, again.model) == ("star_server", LAN, "star-fast")
    assert (again.server_timeout, again.server_parallel, again.server_context_tokens) == (900, 2, 32768)


# ---------------------------------------------------------------- key: keyring / env only

def test_key_comes_from_environment_or_keyring_never_settings(monkeypatch, isolated_credentials, tmp_path):
    settings = server_settings()
    with pytest.raises(ValueError, match="needs its API key"):
        connection_for(settings)
    assert credential_status()["star_server"] is False
    # 1. OS keyring (service "STAR Intelligence", user "star_server")
    save_api_key("star_server", SECRET)
    assert isolated_credentials.store == {("STAR Intelligence", "star_server"): SECRET}
    assert connection_for(settings) == (LAN, SECRET)
    # 2. The environment variable wins over the keyring.
    monkeypatch.setenv("STAR_SERVER_API_KEY", "env-key-0123456789")
    assert connection_for(settings) == (LAN, "env-key-0123456789")
    assert credential_status()["star_server"] is True
    # Nothing key-shaped exists in the settings schema or the saved file.
    assert not [f.name for f in fields(Settings) if f.name not in ("server_context_tokens", "strata_context_tokens") and any(
        word in f.name.lower() for word in ("key", "token", "secret", "password", "bearer", "credential"))]
    path = tmp_path / "settings.json"
    settings.save(path)
    written = path.read_text(encoding="utf-8")
    assert SECRET not in written and "env-key-0123456789" not in written
    assert "api_key" not in written.lower()
    # An attacker-shaped settings file cannot smuggle a key in either.
    path.write_text(json.dumps({**asdict(settings), "server_api_key": SECRET, "api_key": SECRET}), encoding="utf-8")
    loaded = Settings.load(path)
    assert SECRET not in json.dumps(asdict(loaded))
    monkeypatch.delenv("STAR_SERVER_API_KEY")
    providers.clear_api_key("star_server")
    assert get_api_key("star_server") is None


def test_key_is_only_ever_sent_to_a_validated_private_address(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    # Even a settings-like object that skipped Settings.validate() cannot leak the key.
    for bad in ("http://8.8.8.8:8080/v1", "https://api.example.com/v1", "http://169.254.169.254:8080/v1", ""):
        with pytest.raises(ValueError):
            connection_for(SimpleNamespace(provider="star_server", server_endpoint=bad,
                                           endpoint="http://127.0.0.1:8080/v1"))
    # The local brain still gets the placeholder bearer, never the server key.
    local = SimpleNamespace(provider="local", endpoint="http://127.0.0.1:8080/v1", server_endpoint=LAN)
    assert connection_for(local) == ("http://127.0.0.1:8080/v1", "local-only")


def test_server_key_format_is_checked_before_storage(isolated_credentials):
    for value in ("short", "with spaces in it", "line\nbreak-key", "x" * 2049, None, 12345678):
        with pytest.raises(ValueError):
            save_api_key("star_server", value)
    assert isolated_credentials.store == {}


# ---------------------------------------------------------------- timeouts / parallel / context

def test_limits_are_decided_by_kind():
    assert call_limits(Settings()) == providers.CallLimits(95.0, 8.0, 1, True)
    assert call_limits(Settings(provider="groq")) == providers.CallLimits(55.0, 8.0, 2, True)
    lan = call_limits(server_settings())
    assert lan == providers.CallLimits(600.0, 5.0, 1, False)
    assert call_limits(server_settings(server_timeout=900, server_parallel=2)).parallel == 2
    # Tool subagents are capped at two even on a four-slot server.
    assert call_limits(server_settings(server_parallel=4)).parallel == 2


def test_router_gives_the_cpu_server_longer_budgets_and_keeps_the_others():
    def budgets(settings):
        return (select_route(settings, "hi", mode="fast").task_timeout,
                select_route(settings, "Please debug and refactor this function").task_timeout,
                select_route(settings, "Inspect my workspace files", project_tools=True).task_timeout,
                select_route(settings, "Implement it", mode="agent").task_timeout)
    assert budgets(Settings(model="m")) == (85, 180, 180, 480)
    assert budgets(Settings(model="m", provider="groq")) == (55, 100, 180, 480)
    assert budgets(server_settings()) == (600, 1200, 1800, 3600)
    assert budgets(server_settings(server_timeout=120)) == (120, 240, 360, 720)
    assert max(budgets(server_settings(server_timeout=1800))) == 3600
    # Model roles keep working against the one server endpoint.
    route = select_route(server_settings(fast_model="star-fast", reasoning_model="star-deep"),
                         "Please debug and refactor this function")
    assert route.model == "star-deep"


def test_server_context_budget_uses_owner_value_then_reported_value():
    settings = server_settings(context_chars=60000)
    assert model_context_char_budget(settings) == 60000          # unknown: saved budget
    providers.remember_server_limits(LAN, "star-fast", 8192, 2)   # what /props reported
    assert model_context_char_budget(settings) == 2 * (8192 - 1024)
    settings.server_context_tokens = 4096                         # the owner's value wins
    assert model_context_char_budget(settings) == 2 * (4096 - 1024)
    settings.server_context_tokens = 32768
    assert model_context_char_budget(settings) == 60000
    # The managed local router rule is unchanged.
    assert model_context_char_budget(Settings(router_models_dir="C:/ggufs")) == 7168


def test_server_client_ignores_system_proxies_and_uses_server_timeout(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    async def build():
        async with open_client(server_settings(server_timeout=420)) as client:
            return (str(client.base_url), client.api_key, client.max_retries,
                    client.timeout.read, client.timeout.connect, client._client._trust_env)
    assert asyncio.run(build()) == (LAN + "/", SECRET, 0, 420.0, 5.0, False)
    async def local():
        async with open_client(Settings(endpoint="http://127.0.0.1:8080/v1")) as client:
            return str(client.base_url), client.api_key, client.timeout.read, client.timeout.connect
    assert asyncio.run(local()) == ("http://127.0.0.1:8080/v1/", "local-only", 95.0, 8.0)


# ---------------------------------------------------------------- probe_server

def sse(*pieces: str) -> bytes:
    frames = [json.dumps({"choices": [{"delta": {"content": piece}}]}) for piece in pieces]
    return ("".join(f"data: {frame}\n\n" for frame in frames) + "data: [DONE]\n\n").encode()


class FakeServer:
    """A llama.cpp-shaped server behind httpx.MockTransport."""
    def __init__(self, *, key=SECRET, health=200, models=("star-embed", "star-fast"), chat_status=200,
                 chat_body=None, chat_pieces=("STAR ", "is ready."), props=True, error=None):
        self.key, self.health, self.models, self.chat_status = key, health, models, chat_status
        self.chat_body, self.chat_pieces, self.props, self.error = chat_body, chat_pieces, props, error
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)

    def paths(self):
        return [request.url.path for request in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error("simulated network failure", request=request)
        assert request.url.host == "192.168.50.20" and request.url.port == 8080
        path = request.url.path
        if path == "/health":
            return httpx.Response(self.health, json={"status": "ok" if self.health == 200 else "loading model"})
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": {"message": "Invalid API Key", "code": 401}})
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": name, "aliases": []} for name in self.models]})
        if path == "/props":
            if not self.props:
                return httpx.Response(404, json={})
            assert request.url.params["model"] == "star-fast"
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 32768},
                                             "total_slots": 2, "model_path": "/opt/private/model.gguf"})
        if path == "/v1/chat/completions":
            body = json.loads(request.content)
            assert body["stream"] is True and body["max_tokens"] <= 64
            assert [m["role"] for m in body["messages"]] == ["system", "user"]
            if self.chat_status != 200:
                return httpx.Response(self.chat_status, json=self.chat_body or {"error": {"message": "failed"}})
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse(*self.chat_pieces))
        return httpx.Response(404, json={})


def run_probe(monkeypatch, server: FakeServer, settings: Settings | None = None, key: str | None = SECRET):
    if key is not None:
        monkeypatch.setenv("STAR_SERVER_API_KEY", key)
    report = probe_server(settings or server_settings(), transport=server.transport)
    blob = json.dumps(report)
    assert SECRET not in blob, "the server key must never appear in a probe report"
    assert "/opt/private" not in blob and LAN not in blob  # no server paths or address echoed
    assert report["ok"] == (report["code"] == "ok") and report["message"]
    for item in report["steps"]:
        assert set(item) == {"name", "status", "ms", "detail"}
        assert item["status"] in ("ok", "failed", "skipped") and type(item["ms"]) is int and item["ms"] >= 0
    return report


def test_probe_runs_health_models_limits_chat_with_timings(monkeypatch):
    server = FakeServer()
    report = run_probe(monkeypatch, server)
    assert report["ok"] and report["code"] == "ok"
    assert [s["name"] for s in report["steps"]] == ["health", "models", "limits", "chat"]
    assert all(s["status"] == "ok" for s in report["steps"])
    assert server.paths() == ["/health", "/v1/models", "/props", "/v1/chat/completions"]
    assert report["models"] == ["star-embed", "star-fast"] and report["model"] == "star-fast"
    assert (report["context_tokens"], report["slots"]) == (32768, 2)
    assert report["sample"] == "STAR is ready." and type(report["first_token_ms"]) is int
    # The key is not needed for /health, so it is not sent there.
    assert "authorization" not in server.requests[0].headers
    assert all(r.headers["authorization"] == f"Bearer {SECRET}" for r in server.requests[1:])
    # The reported context is remembered for the chat budget (0 = automatic).
    assert providers.server_context_tokens(server_settings()) == 32768
    status = server_status(server_settings())
    assert status["ok"] is True and status["selected"] and status["key_present"]
    assert SECRET not in json.dumps(status) and LAN not in json.dumps(status)


def test_probe_reports_wrong_key_as_401(monkeypatch):
    server = FakeServer()
    report = run_probe(monkeypatch, server, key="wrong-key-0123456789")
    assert report["code"] == "wrong_key" and "401" in report["message"] and "key" in report["message"].lower()
    assert [(s["name"], s["status"]) for s in report["steps"]] == [("health", "ok"), ("models", "failed")]
    assert server.paths() == ["/health", "/v1/models"]  # no chat attempted with a bad key
    assert "wrong-key-0123456789" not in json.dumps(report)
    assert server_status(server_settings())["ok"] is False


def test_probe_reports_loading_as_503(monkeypatch):
    report = run_probe(monkeypatch, FakeServer(health=503))
    assert report["code"] == "loading" and "503" in report["message"] and "loading" in report["message"]
    assert [s["status"] for s in report["steps"]] == ["failed"]
    later = FakeServer(chat_status=503, chat_body={"error": {"message": "Loading model", "code": 503}})
    report = run_probe(monkeypatch, later)
    assert report["code"] == "loading" and report["steps"][-1] == {
        "name": "chat", "status": "failed", "ms": report["steps"][-1]["ms"], "detail": "HTTP 503"}


def test_probe_reports_unknown_model_without_and_with_a_chat_call(monkeypatch):
    # 1. The model list already shows the ID is wrong: do not even try a completion.
    server = FakeServer()
    report = run_probe(monkeypatch, server, server_settings(model="star-missing"))
    assert report["code"] == "unknown_model" and report["models"] == ["star-embed", "star-fast"]
    assert "/v1/chat/completions" not in server.paths()
    # 2. A server that lists nothing proves nothing, so the chat step decides (404).
    server = FakeServer(models=(), chat_status=404,
                        chat_body={"error": {"message": "model not found", "code": 404}})
    report = run_probe(monkeypatch, server, server_settings(model="star-fast"))
    assert report["code"] == "unknown_model" and server.paths()[-1] == "/v1/chat/completions"
    # 3. An alias is accepted, and llama.cpp's router answers 400 "not found".
    class Aliased(FakeServer):
        def handle(self, request):
            if request.url.path == "/v1/models" and request.headers.get("authorization"):
                self.requests.append(request)
                return httpx.Response(200, json={"data": [{"id": "qwen-35b", "aliases": ["star-fast"]}]})
            return super().handle(request)
    server = Aliased(chat_status=400, chat_body={"error": {"code": 400, "message": "model 'star-fast' not found"}})
    report = run_probe(monkeypatch, server)
    assert report["code"] == "unknown_model" and "does not offer this model" in report["message"]
    assert "/v1/chat/completions" in server.paths()


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_probe_reports_unreachable_server(monkeypatch, error):
    server = FakeServer(error=error)
    report = run_probe(monkeypatch, server)
    assert report["code"] == "unreachable" and "Cannot reach STAR Server" in report["message"]
    assert report["steps"][0]["name"] == "health" and report["steps"][0]["status"] == "failed"
    assert len(server.requests) == 1
    assert "Brain tab" not in report["message"] and "download" not in report["message"].lower()


def test_probe_makes_no_request_without_key_or_valid_address(monkeypatch):
    server = FakeServer()
    report = run_probe(monkeypatch, server, key=None)
    assert report["code"] == "no_key" and report["steps"] == [] and server.requests == []
    for bad in ("", "http://8.8.8.8:8080/v1", "http://star.example:8080/v1"):
        settings = SimpleNamespace(provider="star_server", server_endpoint=bad, model="star-fast",
                                   server_timeout=600)
        report = run_probe(monkeypatch, server, settings)
        assert report["code"] == "bad_address" and server.requests == []
    report = run_probe(monkeypatch, server, SimpleNamespace(
        provider="star_server", server_endpoint=LAN, model="two words", server_timeout=600))
    assert report["code"] == "bad_model" and server.requests == []


def test_probe_lists_models_so_setup_can_finish_before_a_model_is_chosen(monkeypatch):
    server = FakeServer()
    report = run_probe(monkeypatch, server, server_settings(model=""))
    assert report["code"] == "no_model" and not report["ok"]
    assert report["models"] == ["star-embed", "star-fast"]
    assert server.paths() == ["/health", "/v1/models"]
    assert "Choose one of its models" in report["message"]


def test_probe_works_before_the_provider_is_switched_and_tolerates_plain_servers(monkeypatch):
    # Still on the local provider: the saved server address can be tested first.
    server = FakeServer(health=404, props=False)
    report = run_probe(monkeypatch, server, Settings(server_endpoint=LAN, model="star-fast"))
    assert report["ok"]
    assert [(s["name"], s["status"]) for s in report["steps"]] == [
        ("health", "skipped"), ("models", "ok"), ("limits", "skipped"), ("chat", "ok")]
    assert report["context_tokens"] is None
    assert server_status(Settings(server_endpoint=LAN, model="star-fast"))["selected"] is False


def test_probe_rejects_empty_reply_and_non_openai_servers(monkeypatch):
    report = run_probe(monkeypatch, FakeServer(chat_pieces=()))
    assert report["code"] == "empty_reply" and report["steps"][-1]["status"] == "failed"
    class NotOpenAI(FakeServer):
        def handle(self, request):
            self.requests.append(request)
            return httpx.Response(200 if request.url.path == "/health" else 404, text="<html>router</html>")
    report = run_probe(monkeypatch, NotOpenAI())
    assert report["code"] == "not_compatible"
    class Reflecting(FakeServer):  # a hostile server that echoes the bearer back
        def handle(self, request):
            if request.url.path == "/v1/chat/completions":
                self.requests.append(request)
                echoed = request.headers["authorization"].split(" ", 1)[1]
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(echoed))
            return super().handle(request)
    report = run_probe(monkeypatch, Reflecting())
    assert report["ok"] and report["sample"] == "[key hidden]"


def test_probe_never_follows_a_redirect_with_the_key(monkeypatch):
    class Redirecting(FakeServer):
        def handle(self, request):
            self.requests.append(request)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(307, headers={"location": "http://8.8.8.8:8080/v1/models"})
    server = Redirecting()
    report = run_probe(monkeypatch, server)
    assert not report["ok"] and all(r.url.host == "192.168.50.20" for r in server.requests)


# ---------------------------------------------------------------- failure wording

class StatusError(Exception):
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        super().__init__(text or f"Error code: {status_code}")


def test_lan_failures_have_their_own_actionable_messages():
    explain = lambda error: explain_model_failure(error, provider_kind="lan")
    assert explain(StatusError(401, SECRET)) == SERVER_FAILURES["wrong_key"]
    assert explain(StatusError(403)) == SERVER_FAILURES["wrong_key"]
    assert explain(StatusError(503, "Loading model")) == SERVER_FAILURES["loading"]
    assert explain(StatusError(404)) == SERVER_FAILURES["unknown_model"]
    assert explain(StatusError(400, "Error code: 400 - model 'x' not found")) == SERVER_FAILURES["unknown_model"]
    assert explain(RuntimeError("Connection error.")) == SERVER_FAILURES["unreachable"]
    assert explain(httpx.ConnectError("")) == SERVER_FAILURES["unreachable"]
    assert explain(httpx.ConnectTimeout("")) == SERVER_FAILURES["unreachable"]
    assert explain(RuntimeError("Request timed out.")) == SERVER_FAILURES["timeout"]
    assert explain(httpx.ReadTimeout("")) == SERVER_FAILURES["timeout"]
    assert explain(StatusError(429)) == SERVER_FAILURES["busy"]
    assert "HTTP 500" in explain(StatusError(500, "Error code: 500 - boom"))
    assert "HTTP 400" in explain(StatusError(400, "Error code: 400 - bad template"))
    assert "context" in explain(RuntimeError("the request exceeds the available context size"))
    assert "stopped" in explain(RuntimeError("STAR task cancelled by user")).lower()
    assert "STAR Server timeout" in explain(TimeoutError("STAR exceeded its 600s task budget."))
    response = httpx.Response(401, request=httpx.Request("GET", LAN + "/models"))
    assert explain(httpx.HTTPStatusError("401", request=response.request, response=response)) \
        == SERVER_FAILURES["wrong_key"]
    for message in [*SERVER_FAILURES.values(), explain(ValueError("anything else"))]:
        lowered = message.lower()
        assert "brain tab" not in lowered and "download" not in lowered and "star brain" not in lowered
        assert SECRET not in message
        assert "STAR Server" in message or "address" in lowered
    # The on-device wording names the page that exists (Model), never the removed Brain tab.
    local = explain_model_failure(RuntimeError("Connection error."))
    assert local.startswith("Cannot reach STAR Brain.") and "Model page" in local and "Brain tab" not in local
    assert "API key" in explain_model_failure(StatusError(401))


def test_missing_model_message_never_sends_a_server_user_to_a_download():
    lan = missing_model_message(server_settings(model=""))
    assert "STAR Server" in lan and "Test server" in lan
    assert "download" not in lan.lower() and "STAR Brain" not in lan
    assert "STAR Server" in missing_model_message(server_settings(model=""), teams=True)
    assert missing_model_message(Settings()) == "STAR Brain is offline. Go to STAR Brain and start your model."
    assert missing_model_message(Settings(), teams=True) == "Start STAR Brain before running a specialist team"
    assert "STAR Brain" in missing_model_message(SimpleNamespace(provider="not-a-provider"))


def test_real_response_test_goes_to_the_server_with_its_key(monkeypatch):
    import openai
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    seen = {}
    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            async def create(**request):
                seen["request"] = request
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)
    with pytest.raises(RuntimeError, match="STAR Server returned no visible text"):
        asyncio.run(probe_chat_endpoint(server_settings(server_timeout=300)))
    assert seen["base_url"] == LAN and seen["api_key"] == SECRET and seen["max_retries"] == 0
    assert seen["timeout"].read == 300.0 and seen["http_client"]._trust_env is False
    assert seen["request"]["model"] == "star-fast"
    asyncio.run(seen["http_client"].aclose())
