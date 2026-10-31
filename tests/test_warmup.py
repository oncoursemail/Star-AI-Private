"""The background server check and prompt-cache priming (star/warmup.py).

It must send exactly the start of the next real request, ask for one token,
stay off cloud providers, stop at once when asked, and leave no trace: no
message, no run record, no analytics row.
"""
import asyncio
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

import star.desktop_core as core
import star.model_health as model_health
import star.warmup as warmup
from star.agent import FAST_RULES
from star.desktop_core import Conversations, Settings, run_task
from star.memory import Memory
from star.model_health import probe_server, server_status
from star.providers import PROVIDERS
from star.warmup import PRIME_TEXT, Warmer, prefix_request, warm_up

LAN = "http://192.168.50.20:8080/v1"
SECRET = "sk-star-test-0123456789"


class Models:
    def __init__(self, answer=None):
        self.requests, self.answer, self.cancelled = [], answer, False

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        if self.answer == "hang":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if isinstance(self.answer, Exception):
            raise self.answer
        if kwargs.get("stream"):
            async def stream():
                yield SimpleNamespace(choices=[], timings={"prompt_n": 412, "cache_n": 3})
            return stream()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="real answer", tool_calls=None))])


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    models = Models()
    for module in (core, warmup):
        monkeypatch.setattr(module, "open_client", lambda settings, **_: Client(models))
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    chats = Conversations(home / "conversations.sqlite3")
    chat = chats.new_chat("STAR")
    for role, text in (("user", "How do I anchor a part?"), ("assistant", "Set Anchored to true."),
                       ("user", "And weld two parts?"), ("assistant", "Use a WeldConstraint.")):
        chats.add("STAR", role, text, chat_id=chat)
    memory = Memory(home / "checkpoints.sqlite3")
    memory.put("STAR::chat::" + chat, "Checkpoint: the obby has three stages.")
    memory.close()
    yield SimpleNamespace(models=models, home=home, chats=chats, chat=chat, settings=Settings(model="qwen-test"))
    chats.close()


def footprint(home):
    """Everything a turn would leave behind."""
    with sqlite3.connect(home / "conversations.sqlite3") as db:
        rows = db.execute("SELECT id,role,body FROM messages ORDER BY id").fetchall()
    return rows, sorted(p.name for p in home.iterdir())


def test_warm_up_sends_exactly_the_start_of_the_next_message(desk):
    report = warm_up(desk.settings, home=desk.home, chat_id=desk.chat)
    primed = desk.models.requests[0]
    assert report["primed"] is True and report["history_messages"] == 4
    assert report["prompt_tokens_read"] == 412 and report["prompt_tokens_cached"] == 3
    assert primed["max_tokens"] == 1 and primed["stream"] is True and "tools" not in primed
    assert primed["extra_body"]["cache_prompt"] is True
    assert primed["messages"][-1]["content"] == [{"type": "text", "text": PRIME_TEXT}]
    # Now the owner sends a real message in the same chat.
    desk.chats.add("STAR", "user", "Thanks, what next?", chat_id=desk.chat)
    run_task(desk.settings, "Thanks, what next?", mode="fast", chat_id=desk.chat)
    real = desk.models.requests[1]
    assert json.dumps(real["messages"][:-1]) == json.dumps(primed["messages"][:-1])   # byte-identical start
    assert real["model"] == primed["model"] and real["extra_body"] == primed["extra_body"]
    system = real["messages"][0]["content"]
    assert system.startswith(FAST_RULES) and "the obby has three stages" in system
    assert [m["role"] for m in real["messages"]] == ["system", "user", "assistant", "user", "assistant", "user"]


def test_warm_up_persists_nothing(desk):
    before = footprint(desk.home)
    assert warm_up(desk.settings, home=desk.home, chat_id=desk.chat)["primed"] is True
    assert footprint(desk.home) == before          # no message, no runs/ folder, no analytics database
    assert "runs" not in before[1] and "analytics.sqlite3" not in before[1]
    # An empty profile stays empty: nothing is created just to warm up.
    empty = desk.home.parent / "fresh"
    empty.mkdir()
    assert warm_up(desk.settings, home=empty)["primed"] is True
    assert list(empty.iterdir()) == []
    assert [m["role"] for m in desk.models.requests[-1]["messages"]] == ["system", "user"]


def test_warm_up_never_touches_a_cloud_provider(desk, monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("a cloud provider must not be contacted by the warm-up")
    monkeypatch.setattr(warmup, "open_client", forbidden)
    monkeypatch.setattr(warmup, "probe_server", forbidden)
    for name in PROVIDERS:
        monkeypatch.setenv(PROVIDERS[name].env_var, "key-0123456789")
        report = warm_up(Settings(provider=name, model=PROVIDERS[name].suggested_model), home=desk.home)
        assert report["skipped"] == "cloud" and report["primed"] is False
    assert warm_up(Settings(model=""), home=desk.home)["skipped"] == "no_model"
    assert desk.models.requests == []


def test_warm_up_stops_when_a_real_request_starts(desk):
    desk.models.answer = "hang"
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    began = time.monotonic()
    report = warm_up(desk.settings, home=desk.home, chat_id=desk.chat, cancel_event=cancel)
    assert time.monotonic() - began < 3
    assert report["cancelled"] is True and report["primed"] is False
    assert desk.models.cancelled is True           # the HTTP request was dropped, not left running
    # Already cancelled before it began: no request at all.
    desk.models.requests.clear()
    assert warm_up(desk.settings, home=desk.home, cancel_event=cancel)["cancelled"] is True
    assert desk.models.requests == []


def test_warm_up_never_raises(desk):
    class Down(Exception):
        status_code = 503
    desk.models.answer = Down("loading")
    report = warm_up(desk.settings, home=desk.home, chat_id=desk.chat)
    assert report["primed"] is False and report["error"] == "Down"


def test_a_server_that_refuses_cache_fields_is_primed_without_them(desk):
    class Refused(Exception):
        status_code = 400
    answers = [Refused("unknown field")]
    original = desk.models.create

    async def create(**kwargs):
        if answers:
            desk.models.requests.append(dict(kwargs))
            raise answers.pop()
        return await original(**kwargs)
    desk.models.create = create
    assert warm_up(desk.settings, home=desk.home)["primed"] is True
    assert "extra_body" in desk.models.requests[0] and "extra_body" not in desk.models.requests[1]


# ------------------------------------------------------------------ STAR Server

def lan_settings():
    return Settings(provider="star_server", server_endpoint=LAN, model="star-fast")


def lan_transport(seen, *, key=SECRET):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.headers.get("authorization") != f"Bearer {key}":
            return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "star-fast"}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 32768}, "total_slots": 2})
        raise AssertionError("the startup check must not send a chat completion of its own")
    return httpx.MockTransport(handle)


def test_startup_check_is_cheap_and_truthful_then_primes_one_slot(desk, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    settings, seen, order = lan_settings(), [], []
    # Other tests in this xdist worker may have probed this same mock LAN
    # endpoint. A fresh app startup starts with no prior in-process status.
    monkeypatch.setattr(model_health, "_LAST_SERVER_CHECK", {})
    assert server_status(settings)["ok"] is None                      # "Not checked"
    report = warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen),
                     on_checked=lambda found: order.append(("checked", found["ok"], len(desk.models.requests))))
    assert seen == [("GET", "/health"), ("GET", "/v1/models"), ("GET", "/props")]
    assert order == [("checked", True, 0)]                            # reported before the slow priming request
    assert report["ok"] is True and report["primed"] is True
    assert server_status(settings)["ok"] is True                      # the light is now truthful
    extra = desk.models.requests[0]["extra_body"]
    assert extra["cache_prompt"] is True and extra["id_slot"] in (0, 1)   # /props said two slots
    assert SECRET not in json.dumps(report)


def test_startup_check_failure_is_reported_and_nothing_is_primed(desk, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "wrong-key-0123456789")
    settings, seen = lan_settings(), []
    report = warm_up(settings, home=desk.home, transport=lan_transport(seen))
    assert report["ok"] is False and report["code"] == "wrong_key" and report["primed"] is False
    assert server_status(settings)["ok"] is False and desk.models.requests == []


def test_probe_server_without_chat_stops_after_limits(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    seen = []
    report = probe_server(lan_settings(), transport=lan_transport(seen), chat=False)
    assert report["ok"] is True and [step["name"] for step in report["steps"]] == ["health", "models", "limits"]
    assert report["slots"] == 2 and report["first_token_ms"] is None


# ------------------------------------------------------------------ Warmer

def test_warmer_runs_off_the_calling_thread_and_one_at_a_time():
    started, release, seen = threading.Event(), threading.Event(), []

    def slow(settings, *, home, chat_id, cancel_event, on_checked, check):
        seen.append((threading.current_thread().name, cancel_event))
        started.set()
        release.wait(5)
        return {"primed": not cancel_event.is_set()}
    warmer, reports = Warmer(run=slow), []
    first = warmer.start(lambda: ("settings", "home", "chat"), on_done=reports.append)
    assert started.wait(5) and first is not threading.current_thread()
    started.clear()
    second = warmer.start(lambda: ("settings", "home", "chat"), on_done=reports.append)
    assert started.wait(5)
    assert seen[0][1].is_set() and not seen[1][1].is_set()            # the newer one cancelled the older one
    warmer.cancel()                                                   # what any real request does
    assert seen[1][1].is_set()
    release.set()
    first.join(5), second.join(5)
    assert reports == [{"primed": False}, {"primed": False}]
    assert all(name == "star-warm-up" for name, _ in seen)


def test_warmer_swallows_every_failure():
    def broken():
        raise OSError("settings file unreadable")
    reports = []
    Warmer().start(broken, on_done=reports.append).join(5)
    assert reports == [{"primed": False, "skipped": "error"}]


def test_a_request_that_could_not_be_built_does_not_turn_the_light_red(desk, monkeypatch):
    """Found in review: any failure before the request was sent was blamed on the server.

    The check has just passed. A chat database that cannot be read is a local
    problem; the server was never asked, so its status must stay as checked.
    """
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    settings, seen = lan_settings(), []
    broken = desk.home.parent / "broken"
    broken.mkdir()
    (broken / "conversations.sqlite3").write_bytes(b"this is not a database " * 64)
    report = warm_up(settings, home=broken, chat_id=desk.chat, transport=lan_transport(seen))
    assert report["primed"] is False and report["skipped"] == "no_request"
    assert desk.models.requests == []                       # nothing was sent
    assert report["ok"] is True and server_status(settings)["ok"] is True
    # A request that was sent and failed still turns it red.
    desk.models.answer = ConnectionError("refused")
    assert warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen))["ok"] is False
    assert server_status(settings)["ok"] is False


# ------------------------------------------------------------------ issue 118: another client's slot

def busy_probe(busy, asked=None):
    """A stand-in for providers.look_for_busy_slots: `busy` maps a model to the slots generating there."""
    async def probe(settings, model, *, conversation=""):
        if asked is not None:
            asked.append((model, conversation))
        return frozenset(busy.get(model, ()))
    return probe


def test_warm_up_never_pins_a_slot_another_client_is_generating_in(desk, monkeypatch):
    # 2026-10-16 (issue 118): a warm-up pinned to a slot where another client was generating made the brain's
    # llama.cpp (before b11583) load the warm-up's cached prompt into that busy slot; the other client's answer
    # went on with the wrong context (a Roblox script turned into text about Script vs LocalScript).
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    settings, seen, asked = lan_settings(), [], []
    assert warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen),
                   probe=busy_probe({}))["primed"] is True
    first = desk.models.requests[0]
    model, slot = first["model"], first["extra_body"]["id_slot"]
    desk.models.requests.clear()

    report = warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen),
                     probe=busy_probe({model: {slot}}, asked))
    assert report["skipped"] == "slot_busy" and report["primed"] is False and report["ok"] is True
    assert desk.models.requests == []                                # nothing sent into the busy slot
    assert asked and asked[0][0] == model and asked[0][1]            # asked about that model, as a named check

    # Only the other slot busy: the warm-up goes to the chat's own slot as before.
    report = warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen),
                     probe=busy_probe({model: {1 - slot}}))
    assert report["primed"] is True and desk.models.requests[0]["extra_body"]["id_slot"] == slot


def test_a_busy_slot_of_the_second_model_skips_only_that_warm_up(desk, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    settings, seen = lan_settings(), []
    monkeypatch.setattr(warmup, "prefix_requests", lambda *a: [
        {"model": "star-voice", "messages": [{"role": "user", "content": "."}], "tools": None,
         "extras": {"cache_prompt": True, "id_slot": 0}},
        {"model": "star-fast", "messages": [{"role": "user", "content": "."}], "tools": None,
         "extras": {"cache_prompt": True, "id_slot": 1}}])
    report = warm_up(settings, home=desk.home, chat_id=desk.chat, transport=lan_transport(seen),
                     probe=busy_probe({"star-fast": {1}}))
    assert report["primed"] is True and "also_primed" not in report
    assert [request["model"] for request in desk.models.requests] == ["star-voice"]


def test_a_failed_busy_check_never_stops_the_warm_up(desk, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", SECRET)
    async def broken(*_a, **_k):
        raise RuntimeError("no answer")
    report = warm_up(lan_settings(), home=desk.home, chat_id=desk.chat, transport=lan_transport([]), probe=broken)
    assert report["primed"] is True
