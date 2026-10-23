"""Offline tests for STAR's optional Strata/Qwen specialist."""
import asyncio
from types import SimpleNamespace
import pytest

from star.strata_backend import BackgroundClient, RoutingClient, choose, probe, request_extras, validate_endpoint
from star.strata_loop_guard import StrataRepetitionError


def settings(**changes):
    base = dict(
        provider="local", strata_enabled=True, strata_endpoint="http://127.0.0.1:8082/v1",
        strata_model="strata", strata_reasoning="auto", strata_context_tokens=32768,
        strata_timeout=900, strata_vision_enabled=True, context_chars=26000,
    )
    base.update(changes)
    return SimpleNamespace(**base)


def route(profile="reasoning", **changes):
    base = dict(profile=profile, response_tokens=1600, task_timeout=180, use_tools=False)
    base.update(changes)
    return SimpleNamespace(**base)


def test_saved_settings_are_backward_compatible_and_validate_strata():
    from star.desktop_core import Settings
    cfg = Settings()
    assert cfg.strata_enabled is False
    assert cfg.strata_endpoint == "http://127.0.0.1:8082/v1"
    cfg.strata_enabled = True
    cfg.strata_reasoning = "high"
    cfg.strata_context_tokens = 65536
    cfg.validate()
    cfg.strata_endpoint = "http://192.168.1.2:8080/v1"
    with pytest.raises(ValueError, match="loopback"):
        cfg.validate()


def test_routes_complex_work_but_not_fast_or_simple_chat():
    plan = choose(settings(), route("reasoning"), "debug this", mode="auto")
    assert plan.active and plan.model == "strata"
    assert plan.reasoning_effort == "medium"
    assert plan.response_tokens >= 4096
    assert plan.context_chars > 26000
    assert choose(settings(), route("fast"), "hello", mode="auto").active is False
    assert choose(settings(), route("roblox"), "build it", mode="fast").active is False
    assert choose(settings(strata_enabled=False), route("agent"), "fix it", mode="agent").active is False


def test_roblox_agent_get_more_reasoning_and_budget():
    roblox = choose(settings(), route("roblox"), "Fix Roblox replication", mode="auto")
    agent = choose(settings(), route("agent", use_tools=True, task_timeout=480), "Finish project", mode="agent")
    assert roblox.reasoning_effort == "high" and roblox.response_tokens >= 6144
    assert agent.reasoning_effort == "high" and agent.response_tokens >= 8192
    assert agent.task_timeout >= 1800
    assert request_extras(agent) == {
        "reasoning_effort": "high", "top_k": 20,
        "reasoning_budget_tokens": int(agent.response_tokens * 0.60),
    }


def test_owner_can_reduce_reasoning_and_disable_vision():
    plan = choose(settings(strata_reasoning="none"), route("reasoning"), "explain", mode="auto")
    assert plan.reasoning_effort == "none" and plan.temperature == 0.7 and plan.top_p == 0.8
    assert request_extras(plan) == {
        "reasoning_effort": "none", "top_k": 20, "presence_penalty": 1.5,
    }
    vision = choose(settings(), route("vision"), "inspect screenshot", mode="auto", image_count=1)
    assert vision.active and vision.reasoning_effort == "medium" and vision.response_tokens >= 4096
    assert not choose(settings(strata_vision_enabled=False), route("vision"), "inspect",
                      mode="auto", image_count=1).active


@pytest.mark.parametrize("bad", [
    "https://example.com/v1", "http://192.168.1.2:8080/v1",
    "http://127.0.0.1:80/v1", "http://localhost:8082/not-v1", "http://user@127.0.0.1:8082/v1",
])
def test_endpoint_is_loopback_only(bad):
    with pytest.raises(ValueError):
        validate_endpoint(bad)
    assert validate_endpoint("http://127.0.0.1:8082/v1") == "http://127.0.0.1:8082/v1"


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, replies):
        self.chat = SimpleNamespace(completions=FakeCompletions(replies))


class BrokenStream:
    def __aiter__(self):
        return self
    async def __anext__(self):
        raise ConnectionError("server disconnected")


def test_background_helpers_use_low_reasoning_without_overriding_callers():
    raw = FakeClient([{"ok": 1}, {"ok": 2}])
    client = BackgroundClient(raw)
    asyncio.run(client.chat.completions.create(model="strata", messages=[]))
    asyncio.run(client.chat.completions.create(
        model="strata", messages=[], temperature=0.2,
        extra_body={"reasoning_effort": "none"}))
    first, second = raw.chat.completions.calls
    assert first["extra_body"] == {
        "reasoning_effort": "low", "top_k": 20, "reasoning_budget_tokens": 425,
    }
    assert first["temperature"] == 1.0 and first["top_p"] == 0.95
    assert second["temperature"] == 0.2
    assert second["extra_body"] == {
        "reasoning_effort": "none", "top_k": 20, "presence_penalty": 1.5,
    }


def test_probe_uses_no_thinking_and_does_not_change_saved_settings(monkeypatch):
    from star import providers
    from star.desktop_core import Settings

    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Strata is ready."))])
    raw = FakeClient([completion])

    class Opened:
        async def __aenter__(self): return raw
        async def __aexit__(self, *args): return False

    monkeypatch.setattr(providers, "open_client", lambda *args, **kwargs: Opened())
    cfg = Settings(model="resident-small")
    result = asyncio.run(probe(cfg, endpoint="http://127.0.0.1:8082/v1", model="strata"))
    assert result["ok"] and result["model"] == "strata"
    call = raw.chat.completions.calls[0]
    assert call["extra_body"] == {
        "reasoning_effort": "none", "top_k": 20, "presence_penalty": 1.5,
    }
    assert call["temperature"] == 0.7 and call["top_p"] == 0.8
    assert cfg.model == "resident-small" and cfg.endpoint == "http://127.0.0.1:8080/v1"


def test_falls_back_before_output_and_stays_on_resident_model():
    primary = FakeClient([ConnectionError("connection refused")])
    fallback = FakeClient([{"ok": 1}, {"ok": 2}])
    events = []
    client = RoutingClient(primary, fallback, strata_model="strata", fallback_model="qwen-small",
                           on_fallback=lambda exc: events.append(type(exc).__name__))
    first = asyncio.run(client.chat.completions.create(
        model="strata", messages=[], extra_body={"reasoning_effort": "high"}))
    second = asyncio.run(client.chat.completions.create(model="strata", messages=[]))
    assert first == {"ok": 1} and second == {"ok": 2}
    assert events == ["ConnectionError"]
    assert fallback.chat.completions.calls[0]["model"] == "qwen-small"
    assert "extra_body" not in fallback.chat.completions.calls[0]
    assert "top_p" not in fallback.chat.completions.calls[0]
    assert fallback.chat.completions.calls[0]["temperature"] == 0.0


def test_stream_can_fail_over_before_first_chunk():
    primary = FakeClient([BrokenStream()])
    fallback = FakeClient([SimpleNamespace(__aiter__=lambda self: self)])
    # Use a small real async iterator for the fallback.
    class One:
        def __init__(self): self.done = False
        def __aiter__(self): return self
        async def __anext__(self):
            if self.done: raise StopAsyncIteration
            self.done = True
            return "fallback-chunk"
    fallback = FakeClient([One()])
    client = RoutingClient(primary, fallback, strata_model="strata", fallback_model="small")
    async def run():
        stream = await client.chat.completions.create(model="strata", messages=[], stream=True)
        return [item async for item in stream]
    assert asyncio.run(run()) == ["fallback-chunk"]


def test_background_legacy_greedy_does_not_trigger_qwen_loop_prone_sampling():
    raw = FakeClient([{"ok": True}])
    client = BackgroundClient(raw)
    asyncio.run(client.chat.completions.create(
        model="strata", messages=[], temperature=0, max_tokens=256))
    sent = raw.chat.completions.calls[0]
    assert sent["temperature"] == 1.0
    assert sent["extra_body"]["reasoning_budget_tokens"] == 128


class TextChunks:
    def __init__(self, fragments, *, reasoning=True):
        self.fragments = iter(fragments)
        self.reasoning = reasoning
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            fragment = next(self.fragments)
        except StopIteration:
            raise StopAsyncIteration from None
        delta = (SimpleNamespace(reasoning_content=fragment, content=None)
                 if self.reasoning else SimpleNamespace(reasoning_content=None, content=fragment))
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def aclose(self):
        self.closed = True


def test_728_streaming_reasoning_is_stopped_and_tools_not_replayed():
    sentence = ("Actually, wait: maybe the screenshot is showing the old Disk bar? "
                "No, the screenshot shows both Disk and Steam rows. ")
    primary_stream = TextChunks([sentence] * 200)
    primary = FakeClient([primary_stream])
    fallback = FakeClient([])
    stopped = []
    client = RoutingClient(
        primary, fallback, strata_model="strata", fallback_model="resident",
        on_loop=lambda exc: stopped.append(getattr(exc, "section", "")),
    )
    async def run():
        stream = await client.chat.completions.create(
            model="strata", messages=[], stream=True)
        async for _ in stream:
            pass

    with pytest.raises(StrataRepetitionError):
        asyncio.run(run())
    assert primary_stream.closed
    assert stopped == ["reasoning"]
    assert fallback.chat.completions.calls == []


def test_728_non_thinking_answer_is_also_stopped():
    repeated = ("The timeout issue requires another check of the same server state. " * 200)
    result = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=repeated, reasoning_content=None))])
    client = RoutingClient(
        FakeClient([result]), FakeClient([]),
        strata_model="strata", fallback_model="resident")
    with pytest.raises(StrataRepetitionError):
        asyncio.run(client.chat.completions.create(model="strata", messages=[]))


def test_728_ordinary_long_streaming_code_does_not_false_trigger():
    chunks = [f"local feature_{i} = {{name='item-{i}', enabled=true}}\n"
              for i in range(300)]
    primary = FakeClient([TextChunks(chunks, reasoning=False)])
    client = RoutingClient(primary, FakeClient([]), strata_model="strata",
                           fallback_model="resident")
    async def run():
        stream = await client.chat.completions.create(
            model="strata", messages=[], stream=True)
        return len([item async for item in stream])
    assert asyncio.run(run()) == len(chunks)


def test_728_guard_can_be_disabled_for_legitimate_repetition():
    sentence = "Repeat this line intentionally for a stress test. "
    chunks = [sentence] * 200
    client = RoutingClient(
        FakeClient([TextChunks(chunks, reasoning=False)]), FakeClient([]),
        strata_model="strata", fallback_model="resident", loop_guard=False)
    async def run():
        stream = await client.chat.completions.create(
            model="strata", messages=[], stream=True)
        return len([item async for item in stream])
    assert asyncio.run(run()) == 200
