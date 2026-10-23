"""Offline tests for STAR's optional Strata/Qwen specialist."""
import asyncio
from types import SimpleNamespace
import pytest

from star.strata_backend import BackgroundClient, RoutingClient, choose, probe, request_extras, validate_endpoint


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
    assert request_extras(agent) == {"reasoning_effort": "high", "top_k": 20}


def test_owner_can_reduce_reasoning_and_disable_vision():
    plan = choose(settings(strata_reasoning="none"), route("reasoning"), "explain", mode="auto")
    assert plan.reasoning_effort == "none" and plan.temperature == 0.7 and plan.top_p == 0.8
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
    assert first["extra_body"] == {"reasoning_effort": "low", "top_k": 20}
    assert first["temperature"] == 1.0 and first["top_p"] == 0.95
    assert second["temperature"] == 0.2
    assert second["extra_body"] == {"reasoning_effort": "none"}


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
    assert call["extra_body"] == {"reasoning_effort": "none", "top_k": 20}
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
