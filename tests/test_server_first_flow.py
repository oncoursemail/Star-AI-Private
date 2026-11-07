"""Server-first behaviour: STAR Server stays selected and nothing asks for a local download.

Covers the Qt-free helpers behind the desktop bridge, the brain/router startup
guards, Teams and benchmarks through the server address + key, and the legacy
UI. No network, no real keyring, no model weights.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest

from star import model_health, providers
from star.brain_benchmark import benchmark_target, main as benchmark_main, measure_one
from star.brain_runtime_health import start_model_router, start_verified_brain
from star.desktop_core import Settings, app_data
from star.diagnostics import review_snapshot
from star.inference_benchmark import benchmark_local_model
from star.model_health import SERVER_FAILURES, server_status
from star.providers import KEY_ENV
from star.react_shell import (ALLOWED_ACTIONS, PERMITTED_SETTINGS, _get_state, apply_setting_changes,
                              describe_failure, server_settings_for)
from star.team_service import run_research_team

ROOT = Path(__file__).resolve().parents[1]
LAN = "http://192.168.50.20:8080/v1"
LOOPBACK = "http://127.0.0.1:8080/v1"
SECRET = "sk-star-server-TEST-0123456789abcdef"


class FakeKeyring:
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


class FakeRuntime:
    def __init__(self, *, running=False, router=False):
        self.running, self.router = running, router
        self.started = self.router_started = self.stopped = 0
    def status(self):
        return "running" if self.running else "not started"
    def router_running(self):
        return self.router
    def start(self, *_a, **_kw):
        self.started += 1
        self.running = True
    def start_router(self, *_a, **_kw):
        self.router_started += 1
        self.running = self.router = True
    def stop(self):
        self.stopped += 1
        self.running = self.router = False


def installed():
    return SimpleNamespace(executable="C:/fake/llama-server.exe",
                           model="C:/fake/qwen.gguf", projector="C:/fake/mmproj.gguf")


def test_no_runtime_code_branches_on_the_local_provider_string():
    """Timeouts, parallelism, context and Teams are decided by provider kind."""
    for name in ("desktop_core.py", "brain_router.py", "model_fleet.py", "model_health.py",
                 "team_service.py", "react_shell.py", "brain_runtime_health.py",
                 "inference_benchmark.py"):
        source = (ROOT / "star" / name).read_text(encoding="utf-8")
        for pattern in ("provider == 'local'", 'provider == "local"', "provider != 'local'",
                        'provider != "local"', "provider=='local'", "provider!='local'"):
            assert pattern not in source, f"{name} still compares {pattern}"


# ---------------------------------------------------------------- start brain / router

def test_start_brain_does_not_clobber_star_server(tmp_path):
    settings_file = tmp_path / "settings.json"
    server_settings(server_timeout=900, fast_model="star-fast").save(settings_file)
    runtime = FakeRuntime()
    seen = {}
    def query(probe_settings):
        seen["query"] = (probe_settings.provider, probe_settings.endpoint)
        return ["qwen-local"]
    async def probe(candidate):
        # The readiness check talks to the local engine, never to the server.
        seen["probe"] = (candidate.provider, candidate.endpoint, candidate.model)
        return {"ok": True, "sample": "STAR is ready."}
    result = start_verified_brain(runtime, installed(), settings_file, tmp_path,
                                  model_query=query, chat_probe=probe, sleep=lambda _: None, max_attempts=2)
    after = Settings.load(settings_file)
    assert (after.provider, after.model, after.server_endpoint) == ("star_server", "star-fast", LAN)
    assert (after.server_timeout, after.fast_model) == (900, "star-fast")
    # Only the local fallback's location was recorded.
    assert (after.endpoint, after.llama_server, after.gguf_model) == (
        LOOPBACK, "C:/fake/llama-server.exe", "C:/fake/qwen.gguf")
    assert seen == {"query": ("local", LOOPBACK), "probe": ("local", LOOPBACK, "qwen-local")}
    assert result["fallback_only"] is True and result["provider"] == "star_server"
    assert result["model"] == "qwen-local" and result["chat_ready"] and runtime.started == 1


def test_failed_local_fallback_leaves_server_settings_byte_identical(tmp_path):
    settings_file = tmp_path / "settings.json"
    server_settings().save(settings_file)
    before = settings_file.read_bytes()
    runtime = FakeRuntime()
    async def failing(_):
        raise RuntimeError("Error code: 500 - local engine crashed")
    with pytest.raises(RuntimeError, match="chat test"):
        start_verified_brain(runtime, installed(), settings_file, tmp_path,
                             model_query=lambda _: ["qwen-local"], chat_probe=failing,
                             sleep=lambda _: None, max_attempts=1)
    assert settings_file.read_bytes() == before and runtime.stopped == 1


def test_start_brain_still_selects_local_for_local_and_cloud_users(tmp_path):
    async def probe(_):
        return {"ok": True, "sample": "ok"}
    for provider in ("local", "groq"):
        settings_file = tmp_path / f"{provider}.json"
        Settings(provider=provider, model="previous").save(settings_file)
        result = start_verified_brain(FakeRuntime(), installed(), settings_file, tmp_path,
                                      model_query=lambda _: ["qwen-local"], chat_probe=probe, max_attempts=1)
        after = Settings.load(settings_file)
        assert (after.provider, after.model) == ("local", "qwen-local")
        assert result["fallback_only"] is False and result["provider"] == "local"


def test_router_refuses_to_start_while_star_server_is_selected(tmp_path):
    settings_file = tmp_path / "settings.json"
    server_settings(router_models_dir=str(tmp_path)).save(settings_file)
    before = settings_file.read_bytes()
    runtime = FakeRuntime()
    with pytest.raises(ValueError, match="STAR Server manages its own models"):
        start_model_router(runtime, settings_file, tmp_path, "C:/fake/llama-server.exe",
                           model_query=lambda _: ["a"], sleep=lambda _: None)
    assert runtime.router_started == 0 and settings_file.read_bytes() == before
    Settings(provider="groq", model="x", router_models_dir=str(tmp_path)).save(settings_file)
    with pytest.raises(ValueError, match="Select Local"):
        start_model_router(runtime, settings_file, tmp_path, "C:/fake/llama-server.exe")
    assert runtime.router_started == 0


def test_router_keeps_a_server_selection_made_while_it_was_loading(tmp_path):
    settings_file = tmp_path / "settings.json"
    Settings(model="old-local", router_models_dir=str(tmp_path)).save(settings_file)
    runtime = FakeRuntime()
    def query(_):
        # The owner switches to STAR Server in Settings while the router loads.
        server_settings(router_models_dir=str(tmp_path)).save(settings_file)
        return ["gguf-a", "gguf-b"]
    result = start_model_router(runtime, settings_file, tmp_path, "C:/fake/llama-server.exe",
                                model_query=query, sleep=lambda _: None)
    after = Settings.load(settings_file)
    assert (after.provider, after.model, after.server_endpoint) == ("star_server", "star-fast", LAN)
    assert after.endpoint == LOOPBACK and Path(after.llama_server) == Path("C:/fake/llama-server.exe")
    assert result["provider"] == "star_server" and result["models"] == ["gguf-a", "gguf-b"]


def test_router_local_behaviour_is_unchanged(tmp_path):
    settings_file = tmp_path / "settings.json"
    Settings(model="missing", fast_model="gguf-b", router_models_dir=str(tmp_path)).save(settings_file)
    runtime = FakeRuntime()
    result = start_model_router(runtime, settings_file, tmp_path, "C:/fake/llama-server.exe",
                                model_query=lambda _: ["gguf-a", "gguf-b"], sleep=lambda _: None)
    after = Settings.load(settings_file)
    assert (after.provider, after.model, after.endpoint) == ("local", "gguf-b", LOOPBACK)
    assert result == {"brain_running": True, "model_router_running": True, "model": "gguf-b",
                      "models": ["gguf-a", "gguf-b"], "chat_ready": False, "provider": "local",
                      "note": "Router ready; actual model completion is not yet verified"}
    # Missing folder / engine and a router that never answers still fail closed.
    Settings(model="m").save(settings_file)
    with pytest.raises(ValueError, match="GGUF model folder"):
        start_model_router(FakeRuntime(), settings_file, tmp_path, "C:/fake/llama-server.exe")
    Settings(model="m", router_models_dir=str(tmp_path)).save(settings_file)
    with pytest.raises(RuntimeError, match="Install the verified STAR Brain"):
        start_model_router(FakeRuntime(), settings_file, tmp_path, "")
    silent = FakeRuntime()
    with pytest.raises(TimeoutError):
        start_model_router(silent, settings_file, tmp_path, "C:/fake/llama-server.exe",
                           model_query=lambda _: [], sleep=lambda _: None, max_attempts=3)
    assert silent.stopped == 1 and Settings.load(settings_file).model == "m"


# ---------------------------------------------------------------- desktop bridge helpers

def test_bridge_exposes_test_server_and_only_nonsecret_server_settings(tmp_path):
    assert "testServer" in ALLOWED_ACTIONS and "saveProviderKey" in ALLOWED_ACTIONS
    assert {"server_endpoint", "server_timeout", "server_parallel", "server_context_tokens"} <= PERMITTED_SETTINGS
    assert PERMITTED_SETTINGS <= set(Settings.__dataclass_fields__)
    assert not [name for name in PERMITTED_SETTINGS if name not in ("server_context_tokens", "strata_context_tokens") and any(
        word in name for word in ("key", "token", "secret", "password", "bearer"))]
    # Engine paths stay host-controlled, exactly as before.
    assert not {"llama_server", "gguf_model"} & PERMITTED_SETTINGS
    changed = apply_setting_changes(Settings(), {
        "provider": "star_server", "server_endpoint": LAN, "model": "star-fast", "server_parallel": 2,
        "server_api_key": SECRET, "api_key": SECRET, "llama_server": "C:/evil.exe"})
    assert (changed.provider, changed.server_endpoint, changed.server_parallel) == ("star_server", LAN, 2)
    assert changed.llama_server == "" and not hasattr(changed, "server_api_key")
    path = tmp_path / "settings.json"
    changed.save(path)
    assert SECRET not in path.read_text(encoding="utf-8")
    for bad in ("http://8.8.8.8:8080/v1", "http://star.example:8080/v1", "http://10.0.0.1:8080/v1?k=1"):
        with pytest.raises(ValueError):
            apply_setting_changes(Settings(), {"server_endpoint": bad}).save(path)
    with pytest.raises(ValueError, match="Invalid settings"):
        apply_setting_changes(Settings(), ["provider"])
    assert Settings.load(path).server_endpoint == LAN  # refused saves changed nothing


class StatusError(Exception):
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        super().__init__(text or f"Error code: {status_code}")


class APIConnectionError(Exception):
    pass


def test_bridge_failures_use_server_wording_only_when_the_server_is_selected(tmp_path):
    settings_file = tmp_path / "settings.json"
    server_settings().save(settings_file)
    assert server_settings_for("sendMessage", settings_file).provider == "star_server"
    assert server_settings_for("generateImage", settings_file) is None
    assert describe_failure("sendMessage", StatusError(401, SECRET), settings_file) == SERVER_FAILURES["wrong_key"]
    assert server_status(server_settings())["ok"] is False
    assert describe_failure("testModel", StatusError(503), settings_file) == SERVER_FAILURES["loading"]
    assert describe_failure("sendMessage", StatusError(404), settings_file) == SERVER_FAILURES["unknown_model"]
    assert describe_failure("listModels", httpx.ConnectError(""), settings_file) == SERVER_FAILURES["unreachable"]
    assert describe_failure("runTeam", APIConnectionError("Connection error."), settings_file) \
        == SERVER_FAILURES["unreachable"]
    # Starting the on-device brain is always about the local engine.
    assert "STAR Brain" in describe_failure("startBrain", StatusError(500, "Error code: 500 - x"), settings_file)
    # Configuration errors pass through with their own clear text.
    assert describe_failure("sendMessage", ValueError("STAR Server needs its API key."), settings_file) \
        == "ValueError: STAR Server needs its API key."
    for action in ("sendMessage", "testModel", "listModels", "runTeam", "testModelTeam"):
        text = describe_failure(action, APIConnectionError("Connection error."), settings_file)
        assert "Brain tab" not in text and "download" not in text.lower()
    # On-device users are pointed at the page that exists (Model), never at the removed Brain tab.
    Settings(model="m").save(settings_file)
    local = describe_failure("sendMessage", APIConnectionError("Connection error."), settings_file)
    assert "Model page" in local and "Brain tab" not in local and "STAR Server" not in local
    assert describe_failure("listModels", httpx.ConnectError("boom"), settings_file) == "ConnectError: boom"
    assert describe_failure("sendMessage", StatusError(401), settings_file).startswith("Your selected model provider")
    # A broken settings file never hides the original error.
    settings_file.write_text("{not json", encoding="utf-8")
    assert describe_failure("listModels", RuntimeError("x"), settings_file) == "RuntimeError: x"


def test_bootstrap_state_describes_the_server_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    home = app_data()
    assert tmp_path in home.parents
    home.mkdir(parents=True)
    settings_file = home / "settings.json"
    server_settings().save(settings_file)
    state = _get_state(settings_file, FakeRuntime())
    assert state["settings"]["provider"] == "star_server" and state["settings"]["server_endpoint"] == LAN
    assert state["credentials"]["star_server"] is True
    roles = state["server"].pop("roles")
    assert state["server"] == {"selected": True, "configured": True, "key_present": True,
                               "model_selected": True, "ok": None, "code": "", "checked_at": ""}
    # Before the server has been asked what it offers, every job uses the one configured model.
    assert {entry["role"] for entry in roles} == {"quick", "code", "vision"}
    assert {entry["source"] for entry in roles} == {"default"}
    assert {entry["model"] for entry in roles} == {state["settings"]["model"]}
    # No local brain is installed or running, and the state says so without blocking the server.
    assert state["brain_installed"] is False and state["brain_running"] is False
    assert SECRET not in json.dumps(state, default=str)
    assert SECRET not in settings_file.read_text(encoding="utf-8")
    # A hand-edited provider never breaks startup.
    settings_file.write_text(json.dumps({"provider": "mystery", "model": "m"}), encoding="utf-8")
    assert _get_state(settings_file, FakeRuntime())["server"]["selected"] is False


# ---------------------------------------------------------------- Teams

class Completions:
    def __init__(self):
        self.requests, self.active, self.peak = [], 0, 0
    async def create(self, **kwargs):
        self.requests.append(kwargs)
        self.active += 1
        self.peak = max(self.active, self.peak)
        await asyncio.sleep(0)  # yield to concurrent calls without wall-clock delay
        self.active -= 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="finding"))])


def capture_client(monkeypatch):
    """Record how STAR builds its AsyncOpenAI client, without any network."""
    import openai
    made = {}
    class FakeOpenAI:
        def __init__(self, **kwargs):
            made.update(kwargs)
            made["completions"] = Completions()
            self.chat = SimpleNamespace(completions=made["completions"])
        async def close(self):
            made["closed"] = True
            if "http_client" in made:
                await made["http_client"].aclose()
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)
    return made


def test_teams_run_on_the_server_with_its_address_key_and_slots(monkeypatch, tmp_path):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    made = capture_client(monkeypatch)
    answer, ledger = asyncio.run(run_research_team(
        settings=server_settings(server_parallel=2, server_timeout=420),
        prompt="Plan a responsive inventory UI", home=tmp_path))
    assert answer == "finding" and ledger.completed
    assert made["base_url"] == LAN and made["api_key"] == SECRET and made["max_retries"] == 0
    assert made["timeout"].read == 420.0 and made["http_client"]._trust_env is False and made["closed"]
    assert len(made["completions"].requests) == 4 and ledger.peak_concurrency == 2
    assert all(request["model"] == "star-fast" for request in made["completions"].requests)
    # One server slot means one call at a time, even if two were asked for.
    made = capture_client(monkeypatch)
    _, ledger = asyncio.run(run_research_team(settings=server_settings(server_parallel=1),
                                              prompt="Plan it again", home=tmp_path, parallel=2))
    assert ledger.peak_concurrency == 1


def test_teams_refuse_cloud_and_unconfigured_server_before_any_call(monkeypatch, tmp_path):
    made = capture_client(monkeypatch)
    async def go(settings):
        return await run_research_team(settings=settings, prompt="Check interface", home=tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key-123")
    with pytest.raises(ValueError, match="own hardware"):
        asyncio.run(go(Settings(provider="groq", model="x")))
    with pytest.raises(ValueError, match="needs its API key"):   # server selected, no key saved
        asyncio.run(go(server_settings()))
    with pytest.raises(ValueError):
        asyncio.run(go(SimpleNamespace(provider="star_server", server_endpoint="http://8.8.8.8:8080/v1",
                                       model="x", project="A", validate=lambda: None,
                                       server_timeout=600, server_parallel=1)))
    assert "completions" not in made
    # The on-device path is unchanged: loopback endpoint and the placeholder bearer.
    asyncio.run(run_research_team(endpoint=LOOPBACK, model="local", project="A",
                                  prompt="Check interface", home=tmp_path))
    assert made["base_url"] == LOOPBACK and made["api_key"] == "local-only"
    assert made["timeout"].read == 110.0 and "http_client" not in made


# ---------------------------------------------------------------- benchmarks

def test_benchmark_target_accepts_the_validated_server_with_a_keyring_key(monkeypatch, isolated_credentials):
    assert benchmark_target(None) == (LOOPBACK, "local-only")
    assert benchmark_target("http://localhost:1234/v1/") == ("http://localhost:1234/v1", "local-only")
    with pytest.raises(ValueError):
        benchmark_target(LAN)                       # a LAN address needs the explicit server switch
    with pytest.raises(ValueError, match="API key"):
        benchmark_target(LAN, server=True)          # and a stored key
    isolated_credentials.set_password("STAR Intelligence", "star_server", SECRET)
    assert benchmark_target(LAN, server=True) == (LAN, SECRET)
    assert benchmark_target(LAN + "/", server=True) == (LAN, SECRET)
    for bad in ("http://8.8.8.8:8080/v1", "https://api.example.com/v1", "http://star.example:8080/v1",
                "http://user:pw@192.168.50.20:8080/v1", "http://192.168.50.20:8080/v1?x=1"):
        with pytest.raises(ValueError):
            benchmark_target(bad, server=True)


def stream_server(seen: list):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        frames = [{"choices": [{"delta": {"content": "A regression test "}}]},
                  {"choices": [{"delta": {"content": "guards behaviour."}}], "usage": {"completion_tokens": 7}}]
        body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())
    return httpx.MockTransport(handle)


def test_latency_benchmark_sends_the_server_key_and_never_prints_it(monkeypatch, capsys, tmp_path):
    seen: list[httpx.Request] = []
    with httpx.Client(transport=stream_server(seen)) as client:
        row = measure_one(client, LAN, "star-fast", "hello", api_key=SECRET)
        assert row["actual_completion_tokens"] == 7 and row["output_chars"] == 35
        measure_one(client, LOOPBACK, "qwen", "hello")
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}" and seen[0].url.host == "192.168.50.20"
    assert seen[1].headers["authorization"] == "Bearer local-only"
    # The command line: --server reads the saved address and the key from the environment.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    app_data().mkdir(parents=True)
    server_settings().save(app_data() / "settings.json")
    calls: list[httpx.Request] = []
    real_client = httpx.Client
    made = {}
    def fake_client(**kwargs):
        made.update(kwargs)
        return real_client(transport=stream_server(calls), **{k: v for k, v in kwargs.items() if k != "transport"})
    monkeypatch.setattr("star.brain_benchmark.httpx.Client", fake_client)
    assert benchmark_main(["--server", "--model", "star-fast", "--runs", "1", "--tokens", "16"]) == 0
    printed = capsys.readouterr().out
    report = json.loads(printed)
    assert report["target"] == "star_server" and report["endpoint"] == LAN and report["summary"]["runs"] == 1
    assert SECRET not in printed and calls[0].headers["authorization"] == f"Bearer {SECRET}"
    assert made["trust_env"] is False and made["timeout"].read == 600.0


def test_parallel_benchmark_can_measure_the_server(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    made = capture_client(monkeypatch)
    result = asyncio.run(benchmark_local_model(LAN, "star-fast", requests=4, parallel=2, server=True))
    assert result["successful"] == 4 and result["parallel_limit"] == 2
    assert made["base_url"] == LAN and made["api_key"] == SECRET and made["timeout"].read == 600.0
    assert made["http_client"]._trust_env is False and made["completions"].peak == 2
    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    for endpoint, server in ((LAN, False), ("http://8.8.8.8:8080/v1", True), ("http://star.example:8080/v1", True)):
        with pytest.raises(ValueError):
            asyncio.run(benchmark_local_model(endpoint, "x", client=fake, server=server))
    assert fake.chat.completions.requests == []
    # Loopback keeps its 90 s limit and placeholder bearer.
    made = capture_client(monkeypatch)
    asyncio.run(benchmark_local_model(LOOPBACK, "qwen", requests=1))
    assert made["base_url"] == LOOPBACK and made["api_key"] == "local-only" and made["timeout"].read == 90.0


# ---------------------------------------------------------------- legacy UI and diagnostics

def test_legacy_ui_cannot_wipe_the_server_configuration():
    source = (ROOT / "star" / "desktop.py").read_text(encoding="utf-8")
    compile(source, "desktop.py", "exec")
    # Saving from the diagnostic UI starts from the saved settings instead of a blank Settings().
    assert "new=replace(self.cfg,endpoint=self.endpoint.text().strip()" in source
    assert "new=Settings(endpoint=self.endpoint.text().strip()" not in source
    # Starting the local brain there does not replace the server's model either.
    assert "if not uses_star_server(self.cfg):\n            self.cfg.model=model" in source.replace("\r\n", "\n")


def test_review_bundle_reports_the_server_as_a_boolean_only(monkeypatch, tmp_path):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    files = review_snapshot(tmp_path, server_settings(), "not started")
    configuration = files["configuration.json"]
    assert configuration["inference_provider"] == "star_server"
    assert configuration["star_server_configured"] is True
    assert configuration["provider_credentials_configured"]["star_server"] is True
    blob = json.dumps(files)
    assert SECRET not in blob and "192.168.50.20" not in blob
    assert review_snapshot(tmp_path, Settings(), "not started")["configuration.json"]["star_server_configured"] is False
