"""Offline instant-route decisions, resident-model probes and chat fallback."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import star.desktop_core as core
from star.desktop_core import Conversations, Settings, run_task
from star.instant_route import (
    InstantAnswer, complete_instant, decide_instant_route,
    loaded_local_model, loaded_model_from_listing,
)
from star.react_shell import sanitize_event


BASE = dict(prompt="What is a palindrome?", mode="fast", provider="lan",
            enabled=True, installed=True, loaded_model="small")


@pytest.mark.parametrize(("changes", "expected"), [
    ({}, True),
    ({"mode": "auto"}, True),
    ({"mode": "agent"}, False),
    ({"provider": "local"}, False),
    ({"provider": "cloud"}, False),
    ({"enabled": False}, False),
    ({"installed": False}, False),
    ({"loaded_model": ""}, False),
    ({"attachments": 1}, False),
    ({"tools": True}, False),
    ({"research": True}, False),
    ({"documentation": True}, False),
    ({"deep": True}, False),
    ({"followup": True}, False),
    ({"prompt": ""}, False),
    ({"prompt": "word " * 50}, False),
    ({"prompt": "How do I script an R6 character in Roblox?"}, False),
    ({"prompt": "Write a Python function to reverse a list."}, False),
    ({"prompt": "Look up the latest documentation."}, False),
    ({"prompt": "/deep What is a palindrome?"}, False),
    ({"prompt": "What is\na palindrome?"}, False),
    ({"prompt": "And what about that?"}, False),
    ({"prompt": "What does TweenService do?"}, False),
    ({"prompt": "Why is the sky blue?"}, True),
])
def test_decision_table(changes, expected):
    inputs = BASE | changes
    assert decide_instant_route(**inputs).use_local is expected
    assert decide_instant_route(**inputs) == decide_instant_route(**inputs)


@pytest.mark.parametrize(("listed", "expected"), [
    ([{"id": "small", "status": {"value": "loaded"}},
      {"id": "huge", "status": {"value": "unloaded"}}], "small"),
    ([{"id": "small", "status": {"value": "unloaded"}}], ""),
    ([{"id": "small", "status": {"value": "loading"}}], ""),
    ([{"id": "small", "status": {"value": "loaded", "failed": True}}], ""),
    ([{"id": "small", "status": {"value": "loaded"}},
      {"id": "other", "status": {"value": "loaded"}}], ""),
    ([{"id": "single"}], "single"),
    ([{"id": "single"}, {"id": "other"}], ""),
    ([{"id": "voice", "status": {"value": "loaded"},
      "architecture": {"input_modalities": ["audio"]}}], ""),
    ([{"id": "not valid id", "status": {"value": "loaded"}}], ""),
    ([], ""),
    (None, ""),
])
def test_loaded_model_table(listed, expected):
    assert loaded_model_from_listing(listed) == expected


def test_loopback_probe_never_loads_or_follows_redirects():
    requested = []

    def handler(request):
        requested.append((request.method, str(request.url)))
        return httpx.Response(200, json={"data": [
            {"id": "small", "status": {"value": "loaded"}},
            {"id": "huge", "status": {"value": "unloaded"}},
        ]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            assert await loaded_local_model("http://127.0.0.1:8080/v1", client=client) == "small"
            assert await loaded_local_model("https://example.org/v1", client=client) == ""
    asyncio.run(run())
    assert requested == [("GET", "http://127.0.0.1:8080/v1/models")]


class FakeStream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


def chunk(text="", tokens=None):
    choice = [SimpleNamespace(delta=SimpleNamespace(content=text))] if text else []
    usage = SimpleNamespace(completion_tokens=tokens) if tokens is not None else None
    return SimpleNamespace(choices=choice, usage=usage)


class Completions:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class Client:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_instant_records_actual_first_token_and_throughput_with_fake_clock():
    clock = iter([0.0, 0.08, 0.08, 0.18])
    stream = FakeStream([chunk("Hello"), chunk(" there"), chunk(tokens=3)])
    completions = Completions(stream)
    result = asyncio.run(complete_instant(Client(completions), "small", "Say hello",
                                          clock=lambda: next(clock)))
    assert result == InstantAnswer("Hello there", "small", 80, 20.0, False)
    assert stream.closed
    assert len(completions.requests) == 1
    assert completions.requests[0]["stream"] is True
    assert completions.requests[0]["messages"][-1] == {"role": "user", "content": "Say hello"}


def test_local_model_is_cancelled_on_first_token_timeout():
    class NeverResponds:
        async def create(self, **kwargs):
            await asyncio.Future()

    with pytest.raises(TimeoutError):
        asyncio.run(complete_instant(Client(NeverResponds()), "small", "Hello",
                                      first_token_deadline=0.01, total_deadline=0.1))


def test_partial_local_stream_failure_does_not_produce_an_answer():
    class BrokenStream(FakeStream):
        async def __anext__(self):
            result = await super().__anext__()
            if result is None:
                raise RuntimeError("local stream failed")
            return result

    stream = BrokenStream([chunk("incomplete"), None])
    with pytest.raises(RuntimeError, match="stream failed"):
        asyncio.run(complete_instant(Client(Completions(stream)), "small", "Hello"))
    assert stream.closed


@pytest.fixture
def desk(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(core, "connection_for", lambda *_: ("http://127.0.0.1:8080/v1", "local-only"))
    home = core.app_data()
    chats = Conversations(home / "conversations.sqlite3")
    chat_id = chats.new_chat("STAR")
    settings = Settings(provider="star_server", server_endpoint="http://127.0.0.1:8080/v1",
                        model="server-model", gguf_model="configured.gguf", knowledge_endpoint="off", instant_route_enabled=True)
    events = []
    yield SimpleNamespace(home=home, chats=chats, chat_id=chat_id, settings=settings, events=events)
    chats.close()


def run_saved_turn(desk, question, *, mode="fast", **flags):
    desk.chats.add("STAR", "user", question, chat_id=desk.chat_id)
    answer = run_task(desk.settings, question, chat_id=desk.chat_id, mode=mode,
                      on_event=desk.events.append, **flags)
    desk.chats.add("STAR", "assistant", answer, chat_id=desk.chat_id)
    rows = desk.chats.recent_records("STAR", chat_id=desk.chat_id)
    record = json.loads(next((desk.home / "runs").glob("*/transcript.json")).read_text())
    return answer, rows, record


def test_loaded_local_answer_is_saved_once_and_its_brain_recorded(monkeypatch, desk):
    probes = []
    async def probe(*_):
        probes.append("loaded")
        return "pc-small"
    async def answer(*_):
        return InstantAnswer("A word that reads the same backwards.", "pc-small", 96, 33.2, False)
    monkeypatch.setattr(core, "loaded_local_model", probe)
    monkeypatch.setattr(core, "answer_on_pc", answer)
    monkeypatch.setattr(core, "open_client", lambda *_: pytest.fail("server must not be called"))
    response, rows, artifact = run_saved_turn(desk, "What is a palindrome?")
    assert response.startswith("A word")
    assert probes == ["loaded"]
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[-1]["body"] == response
    assert artifact["answer_stats"] == {
        "brain": "pc", "model": "pc-small", "first_token_ms": 96,
        "tokens_per_second": 33.2, "estimated_tokens": False}
    assert [e["event"] for e in desk.events].count("assistant_delta") == 1
    assert [e["event"] for e in desk.events].count("model_answered") == 1


def test_failed_instant_tries_server_once_with_no_duplicate_row(monkeypatch, desk):
    async def loaded(*_):
        return "pc-small"
    async def failed(*_):
        raise TimeoutError("first token slow")
    monkeypatch.setattr(core, "loaded_local_model", loaded)
    monkeypatch.setattr(core, "answer_on_pc", failed)
    server_calls = []
    class Server:
        async def create(self, **kwargs):
            server_calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Server answer.", tool_calls=None))])
    monkeypatch.setattr(core, "open_client", lambda *_: Client(Server()))
    answer, rows, artifact = run_saved_turn(desk, "What is a palindrome?")
    assert answer == "Server answer."
    assert len(server_calls) == 1
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert artifact["answer_stats"]["brain"] == "server"
    assert artifact["answer_stats"]["model"] == "server-model"
    assert [e["event"] for e in desk.events].count("instant_fallback") == 1
    assert [e["event"] for e in desk.events].count("model_answered") == 1


@pytest.mark.parametrize("flag", [False, None])
def test_instant_disabled_or_uninstalled_never_probes(monkeypatch, desk, flag):
    desk.settings.instant_route_enabled = flag
    monkeypatch.setattr(core, "loaded_local_model", lambda *_: pytest.fail("must not probe"))
    server_calls = []
    class Server:
        async def create(self, **kwargs):
            server_calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Server as selected.", tool_calls=None))])
    monkeypatch.setattr(core, "open_client", lambda *_: Client(Server()))
    answer, rows, _ = run_saved_turn(desk, "What is a palindrome?")
    assert answer == "Server as selected."
    assert len(server_calls) == 1 and len(rows) == 2


@pytest.mark.parametrize("case", ["attachment", "probe_error"])
def test_attachment_and_failed_probe_keep_the_single_server_request(monkeypatch, desk, case):
    probed = []

    async def probe(*_):
        probed.append("called")
        if case == "probe_error":
            raise RuntimeError("PC model endpoint unavailable")
        return "pc-small"

    monkeypatch.setattr(core, "loaded_local_model", probe)
    monkeypatch.setattr(core, "answer_on_pc", lambda *_: pytest.fail("no local answer"))
    requests = []

    class Server:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Server answered once.", tool_calls=None))])

    monkeypatch.setattr(core, "open_client", lambda *_: Client(Server()))
    kwargs = {"attachment_count": 1} if case == "attachment" else {}
    answer, rows, artifact = run_saved_turn(desk, "What is a palindrome?", **kwargs)
    assert answer == "Server answered once."
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert len(requests) == 1
    assert probed == ([] if case == "attachment" else ["called"])
    assert artifact["answer_stats"]["brain"] == "server"


def test_settings_and_sanitized_activity_are_nonsecret(tmp_path):
    for value in (True, False, None):
        settings = Settings(instant_route_enabled=value)
        settings.save(tmp_path / "settings.json")
        assert Settings.load(tmp_path / "settings.json").instant_route_enabled is value
    with pytest.raises(ValueError, match="Instant answers"):
        Settings(instant_route_enabled="yes").validate()
    payload = sanitize_event({"event": "answer_stats", "brain": "pc",
                              "model": "pc-small", "first_token_ms": 96,
                              "tokens_per_second": 33.2, "estimated_tokens": False,
                              "prompt": "must never leak", "secret": "must never leak"})
    assert payload["activity"] == {
        "type": "answer_stats", "brain": "pc", "model": "pc-small",
        "first_token_ms": 96, "tokens_per_second": 33.2, "estimated_tokens": False}
    assert "must never leak" not in str(payload)


def test_default_off_runs_original_server(monkeypatch, desk):
    assert Settings().instant_route_enabled is False
    desk.settings.instant_route_enabled = False
    monkeypatch.setattr(core, "loaded_local_model", lambda *_: pytest.fail("must not probe"))
    calls = []
    class Server:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Server answer.", tool_calls=None))])
    monkeypatch.setattr(core, "open_client", lambda *_: Client(Server()))
    answer, rows, artifact = run_saved_turn(desk, "What is a palindrome?")
    assert answer == "Server answer." and len(calls) == 1
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert artifact["answer_stats"]["brain"] == "server"


def test_decision_overhead_benchmark():
    import time
    count = 20000
    start = time.perf_counter_ns()
    for _ in range(count):
        decide_instant_route(**BASE)
    microseconds = (time.perf_counter_ns() - start) / (count * 1000)
    import warnings
    warnings.warn(f"Instant routing decision overhead: {microseconds:.3f} microseconds/call over {count} calls", stacklevel=1)
    assert microseconds >= 0


def test_general_question_on_the_gpu_lane_is_saved_once(monkeypatch, desk):
    """star/general_mode.py: a general question goes to the mesh router's GPU nodes when one is configured."""
    from star import general_mode
    desk.settings.instant_route_enabled = False
    monkeypatch.setattr(general_mode, "gpu_endpoint", lambda settings: "http://10.1.2.3:8100/v1")  # star:allow
    sent = []

    async def gpu(settings, endpoint, messages, *, max_tokens, temperature, on_delta=None, **_):
        sent.append(messages)
        await on_delta("Pete Conrad, ")
        await on_delta("Apollo 12.")
        return "Pete Conrad, Apollo 12."
    monkeypatch.setattr(general_mode, "gpu_answer", gpu)
    monkeypatch.setattr(core, "open_client", lambda *_: pytest.fail("the brain must not be called"))
    answer, rows, artifact = run_saved_turn(desk, "Who was the third person to walk on the Moon?")
    assert answer == "Pete Conrad, Apollo 12."
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert artifact["answer_stats"]["brain"] == "gpu"
    user = sent[0][-1]["content"]
    assert user.startswith("Who was the third person") and general_mode.NOTE in user
    assert sent[0][0]["role"] == "system" and "Star" in sent[0][0]["content"]
    assert [e["event"] for e in desk.events].count("assistant_delta") == 2


def test_gpu_lane_failure_falls_back_to_the_brain_without_the_note(monkeypatch, desk):
    from star import general_mode
    desk.settings.instant_route_enabled = False
    monkeypatch.setattr(general_mode, "gpu_endpoint", lambda settings: "http://10.1.2.3:8100/v1")  # star:allow

    async def down(*_, **__):
        raise TimeoutError
    monkeypatch.setattr(general_mode, "gpu_answer", down)
    server_calls = []

    class Server:
        async def create(self, **kwargs):
            server_calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Server answer.", tool_calls=None))])
    monkeypatch.setattr(core, "open_client", lambda *_: Client(Server()))
    answer, rows, artifact = run_saved_turn(desk, "Who was the third person to walk on the Moon?")
    assert answer == "Server answer." and len(server_calls) == 1 and len(rows) == 2
    assert artifact["answer_stats"]["brain"] == "server"
    assert general_mode.NOTE not in json.dumps(server_calls[0]["messages"])   # the note is for the GPU lane only
    assert [e["event"] for e in desk.events].count("general_gpu_fallback") == 1
