"""Exercise the actual SDK/fleet transport with in-memory HTTP, never a server."""
import asyncio
import json
import threading

import httpx
import pytest

from star.bulk_operations import OperationCancelled, OperationFailed
from star.bulk_tasks import _call_brain
from star.desktop_core import Settings


def settings():
    return Settings(provider="star_server", server_endpoint="http://10.20.30.40:8080/v1",
                    model="bulk-test-model")


def response(answer="A read-only proposal.", model="bulk-test-model"):
    return httpx.Response(200, json={
        "id": "mock-completion", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": answer}}],
        "usage": {"prompt_tokens": 24, "completion_tokens": 6, "total_tokens": 30},
    })


def install_transport(monkeypatch, handler):
    calls, options, clients = [], [], []
    original = httpx.AsyncClient.__init__

    async def record(request):
        calls.append(request)
        result = handler(request)
        return await result if hasattr(result, "__await__") else result

    def initialize(client, *args, **kwargs):
        options.append({key: kwargs.get(key) for key in ("trust_env", "follow_redirects")})
        kwargs["transport"] = httpx.MockTransport(record)
        original(client, *args, **kwargs)
        clients.append(client)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", initialize)
    return calls, options, clients


def test_real_sdk_uses_exact_endpoint_one_read_only_call_and_closes(monkeypatch):
    calls, options, clients = install_transport(monkeypatch, lambda _: response())
    result = asyncio.run(_call_brain(settings(), "Review this setting", "fake-test-key", threading.Event()))
    assert len(calls) == 1
    assert str(calls[0].url) == "http://10.20.30.40:8080/v1/chat/completions"
    assert calls[0].headers["authorization"] == "Bearer fake-test-key"
    body = json.loads(calls[0].content)
    assert body["model"] == "bulk-test-model"
    assert body["max_tokens"] == 850
    assert body["temperature"] == 0
    assert "tools" not in body and "functions" not in body
    assert body["messages"][0]["role"] == "system"
    assert "read-only worker" in body["messages"][0]["content"]
    assert options == [{"trust_env": False, "follow_redirects": False}]
    assert clients and all(client.is_closed for client in clients)
    assert result["answer"] == "A read-only proposal."
    assert result["verified"] is False
    assert result["receipt"]["observed_match"] is True
    assert result["receipt"]["prompt_tokens"] == 24


@pytest.mark.parametrize("status", [400, 422, 503])
def test_compatibility_and_sdk_failures_never_repeat_transport_or_echo_body(monkeypatch, status):
    calls, _, clients = install_transport(monkeypatch, lambda _: httpx.Response(
        status, json={"error": {"message": "sensitive-provider-response-marker", "type": "server_error"}}))
    with pytest.raises(OperationFailed) as failed:
        asyncio.run(_call_brain(settings(), "Task", "fake-test-key", threading.Event()))
    assert len(calls) == 1
    assert "sensitive-provider-response-marker" not in str(failed.value)
    assert "fake-test-key" not in str(failed.value)
    assert all(client.is_closed for client in clients)


def test_redirect_is_not_followed(monkeypatch):
    calls, _, _ = install_transport(monkeypatch, lambda _: httpx.Response(
        307, headers={"Location": "https://untrusted.invalid/collect"}))
    with pytest.raises(OperationFailed):
        asyncio.run(_call_brain(settings(), "Task", "fake-test-key", threading.Event()))
    assert len(calls) == 1
    assert calls[0].url.host == "10.20.30.40"


def test_reported_wrong_model_is_not_success(monkeypatch):
    calls, _, _ = install_transport(monkeypatch, lambda _: response(model="different-model"))
    with pytest.raises(OperationFailed):
        asyncio.run(_call_brain(settings(), "Task", "fake-test-key", threading.Event()))
    assert len(calls) == 1


def test_local_cancel_closes_the_actual_in_memory_request(monkeypatch):
    stopped = threading.Event()
    cancelled = threading.Event()

    async def pending(_):
        cancelled.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    calls, _, clients = install_transport(monkeypatch, pending)
    with pytest.raises(OperationCancelled, match="remote compute termination is not confirmed"):
        asyncio.run(_call_brain(settings(), "Task", "fake-test-key", cancelled))
    assert len(calls) == 1
    assert stopped.is_set()
    assert all(client.is_closed for client in clients)


def test_large_answer_is_explicitly_bounded(monkeypatch):
    install_transport(monkeypatch, lambda _: response(answer="x" * 5000))
    result = asyncio.run(_call_brain(settings(), "Task", "fake-test-key", threading.Event()))
    assert len(result["answer"]) == 3200
    assert result["answer_truncated"] is True
