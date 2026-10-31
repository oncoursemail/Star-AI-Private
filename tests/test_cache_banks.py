"""Saved project memory (star/cache_banks.py): no network, no model server, no secrets.

The bank must hold only the stable start of a request as the server's template renders it, touch only an empty
slot, restore instead of re-reading when the same start comes back, keep the server's files to a fixed pool, and
stay off without both opt-ins.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from star import cache_banks as banks
import star.warmup as warmup
from star.desktop_core import Settings

SERVER = "http://192.168.50.20:8080/v1"  # star:allow (test address)
KEY = "test-key-not-a-real-key"  # star:allow (test fake)


class FakeServer:
    """GET /slots, /apply-template (ChatML-like), /v1/completions and slot save/restore, recording every call."""

    def __init__(self, state="empty"):
        self.state, self.calls, self.files, self.fail = state, [], {}, set()
        self.slow = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, dict(request.url.params), body,
                           request.headers.get("authorization")))
        if request.method == "GET" and request.url.path == "/slots":
            other = {"id": 0, "is_processing": False, "id_task": 3, "n_prompt_tokens": 900,
                     "prompt": "x" * 20_000}   # a used slot reports its whole last prompt
            mine = {"id": 1, "is_processing": self.state == "busy"}
            if self.state in ("used", "busy"):
                mine.update(id_task=7, n_prompt_tokens=1200, prompt="y" * 20_000)
            return httpx.Response(200, json=[other, mine])
        if request.url.path == "/apply-template":
            tools = "".join(f"<tool>{t['function']['name']}</tool>" for t in body.get("tools") or [])
            prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}{tools if m['role'] == 'system' else ''}"
                             f"<|im_end|>\n" for m in body["messages"]) + "<|im_start|>assistant\n"
            return httpx.Response(200, json={"prompt": prompt})
        if request.url.path == "/v1/completions":
            return httpx.Response(200, json={"choices": [{"text": "x"}], "timings": {"prompt_n": 1100}})
        if request.method == "POST" and request.url.path == "/slots/1":
            action, name = request.url.params["action"], body["filename"]
            if action in self.fail:
                return httpx.Response(400, json={"error": {"message": "failed"}})
            if action == "save":
                self.files[name] = True
                reply = {"n_saved": 1100, "n_written": 64_000_000, "timings": {"save_ms": 210.5}}
            else:
                if name not in self.files:
                    return httpx.Response(400, json={"error": {"message": "no file"}})
                reply = {"n_restored": 1100, "n_read": 64_000_000, "timings": {"restore_ms": 95.0}}
            return httpx.Response(200, json={"id_slot": 1, "filename": name, **reply})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    async def ahandle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/completions" and self.slow is not None:
            while not self.slow.is_set():
                await asyncio.sleep(0.05)
        return self.handle(request)

    def paths(self):
        return [(method, path) for method, path, *_ in self.calls]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv(banks.ENV_ENABLE, "on")
    monkeypatch.setenv(banks.ENV_REVISION, "qwen-test-sha256-11223344")
    monkeypatch.delenv(banks.ENV_MAX, raising=False)
    monkeypatch.setattr(banks, "server_slots", lambda *_: 2)
    monkeypatch.setattr(banks, "connection_for", lambda _: (SERVER, KEY))
    monkeypatch.setattr(banks, "provider_kind", lambda _: "lan")
    settings = Settings(provider="star_server", model="star-fast", server_endpoint=SERVER, project="STAR")
    request = {
        "model": "star-fast",
        "messages": [{"role": "system", "content": "Stable rules\nProject: private notes"},
                     {"role": "user", "content": "first question"},
                     {"role": "assistant", "content": "answer"},
                     {"role": "user", "content": "latest question"}],
        "tools": [{"type": "function", "function": {"name": "tool_one"}}],
        "extras": {"id_slot": 1, "cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}},
    }
    return SimpleNamespace(settings=settings, request=request, home=tmp_path / "home")


def prepare(setup, server, request=None, **kw):
    return asyncio.run(banks.prepare(setup.settings, setup.home, request or setup.request,
                                     transport=httpx.MockTransport(server.ahandle), **kw))


def with_system(request, text):
    return {**request, "messages": [{"role": "system", "content": text}, *request["messages"][1:]]}


def test_off_until_both_opt_ins_are_present(setup, monkeypatch):
    server = FakeServer()
    monkeypatch.setenv(banks.ENV_ENABLE, "yes")
    assert prepare(setup, server) == {"bank": "skipped", "reason": "off"}
    monkeypatch.setenv(banks.ENV_ENABLE, "on")
    monkeypatch.setenv(banks.ENV_REVISION, "???")
    assert prepare(setup, server)["reason"] == "revision"
    assert server.calls == []


def test_only_a_pinned_cached_request_to_own_server(setup, monkeypatch):
    server = FakeServer()
    for slot in (-1, 2, None, True, "1"):
        request = {**setup.request, "extras": {**setup.request["extras"], "id_slot": slot}}
        assert prepare(setup, server, request)["reason"] == "unpinned"
    request = {**setup.request, "extras": {**setup.request["extras"], "cache_prompt": False}}
    assert prepare(setup, server, request)["reason"] == "unpinned"
    assert prepare(setup, server, {**setup.request, "messages": setup.request["messages"][1:]})["reason"] == "no_system"
    monkeypatch.setattr(banks, "server_slots", lambda *_: 1)
    assert prepare(setup, server)["reason"] == "unpinned"
    monkeypatch.setattr(banks, "provider_kind", lambda _: "cloud")
    assert prepare(setup, server)["reason"] == "not_local_server"
    assert server.calls == []


def test_empty_slot_reads_and_banks_only_the_stable_start(setup):
    server = FakeServer()
    report = prepare(setup, server, now=100)
    assert report["bank"] == "saved" and report["tokens"] == 1100 and report["bytes"] == 64_000_000
    assert report["ms"] == 210.5 and type(report["read_ms"]) is int
    assert server.paths() == [("GET", "/slots"), ("POST", "/apply-template"), ("POST", "/apply-template"),
                              ("POST", "/v1/completions"), ("POST", "/slots/1")]
    # Rendered with the request's own system message, tools and template settings, never its history.
    rendered = server.calls[1][3]
    assert rendered["messages"][0] == setup.request["messages"][0] and rendered["tools"] == setup.request["tools"]
    assert rendered["chat_template_kwargs"] == {"preserve_thinking": True} and len(rendered["messages"]) == 2
    sent = server.calls[3][3]
    assert sent["prompt"] == ("<|im_start|>system\nStable rules\nProject: private notes<tool>tool_one</tool>"
                              "<|im_end|>\n<|im_start|>user\n")
    assert sent["max_tokens"] == 1 and sent["id_slot"] == 1 and sent["cache_prompt"] is True
    params, body = server.calls[4][2], server.calls[4][3]
    assert params == {"action": "save"} and body["model"] == "star-fast"
    assert banks.BANK_NAME.fullmatch(body["filename"]) and server.calls[4][4] == "Bearer " + KEY
    index = (setup.home / "cache-banks" / "index.json").read_text()
    assert "private notes" not in index and KEY not in index and "192.168" not in index  # star:allow (test address)


def test_same_start_comes_back_restored_from_any_chat(setup):
    server = FakeServer()
    prepare(setup, server, now=100)
    server.calls.clear()
    other_chat = {**setup.request, "messages": [setup.request["messages"][0], {"role": "user", "content": "hi"}]}
    report = prepare(setup, server, other_chat, now=200)
    assert report == {"bank": "restored", "tokens": 1100, "bytes": 64_000_000, "ms": 95.0}
    assert ("POST", "/v1/completions") not in server.paths()
    assert server.calls[-1][2] == {"action": "restore"}


def test_used_or_busy_slot_is_left_alone(setup):
    for state in ("used", "busy"):
        server = FakeServer(state)
        assert prepare(setup, server)["reason"] == "slot_" + state
        assert server.paths() == [("GET", "/slots")]


def test_changed_start_is_a_new_bank_and_the_pool_reuses_the_oldest_name(setup, monkeypatch):
    monkeypatch.setenv(banks.ENV_MAX, "2")
    server = FakeServer()
    first = prepare(setup, server, now=1)
    changed_tools = {**setup.request, "tools": [{"type": "function", "function": {"name": "tool_two"}}]}
    assert prepare(setup, server, changed_tools, now=2)["bank"] == "saved"
    names = [body["filename"] for method, path, params, body, _ in server.calls
             if path == "/slots/1" and params["action"] == "save"]
    assert len(set(names)) == 2 and first["bank"] == "saved"
    prepare(setup, server, now=3)   # the first start again: restored, now the most recently used
    prepare(setup, server, with_system(setup.request, "Another project"), now=4)
    names = [body["filename"] for method, path, params, body, _ in server.calls
             if path == "/slots/1" and params["action"] == "save"]
    assert names[2] == names[1]     # the least recently used bank's file is overwritten
    index = json.loads((setup.home / "cache-banks" / "index.json").read_text())["banks"]
    assert len(index) == 2 and sorted(v["file"] for v in index.values()) == sorted(set(names))


def test_missing_server_file_is_built_again_and_bad_receipts_are_not_recorded(setup):
    server = FakeServer()
    prepare(setup, server, now=1)
    server.files.clear()            # the server lost its files
    assert prepare(setup, server, now=2)["bank"] == "saved"
    server.fail.add("save")
    report = prepare(setup, server, with_system(setup.request, "Other rules"), now=3)
    assert report["bank"] == "skipped" and report["reason"] == "save_failed"
    index = json.loads((setup.home / "cache-banks" / "index.json").read_text())["banks"]
    assert len(index) == 1


def test_cancel_before_and_during_the_read(setup):
    server = FakeServer()
    cancel = threading.Event()
    cancel.set()
    assert prepare(setup, server, cancel_event=cancel)["reason"] == "cancelled" and server.calls == []
    cancel.clear()
    server.slow = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    began = time.monotonic()
    report = prepare(setup, server, cancel_event=cancel)
    server.slow.set()
    assert report["reason"] == "cancelled" and time.monotonic() - began < 3
    assert not (setup.home / "cache-banks").exists()


def test_index_that_is_invalid_never_restores(setup):
    folder = setup.home / "cache-banks"
    folder.mkdir(parents=True)
    (folder / "index.json").write_text("{not json")
    server = FakeServer()
    assert prepare(setup, server)["bank"] == "saved"


def test_warm_up_restores_before_priming(setup, monkeypatch):
    monkeypatch.setattr(warmup, "prefix_requests", lambda *_: [setup.request])
    monkeypatch.setattr(warmup, "probe_server", lambda *a, **kw: {"ok": True, "code": "ok"})
    monkeypatch.setattr(warmup, "provider_kind", lambda _: "lan")

    async def not_busy(*a, **kw):
        return False
    monkeypatch.setattr(warmup, "_slot_busy", not_busy)
    calls = []

    async def fake_prepare(settings, home, request, **kw):
        calls.append("bank")
        return {"bank": "restored", "tokens": 1100, "bytes": 1, "ms": 90.0}

    async def fake_prime(*a):
        calls.append("prime")
        return {"primed": True}
    monkeypatch.setattr(banks, "prepare", fake_prepare)
    monkeypatch.setattr(warmup, "_prime", fake_prime)
    report = warmup.warm_up(setup.settings, home=setup.home, chat_id="c001")
    assert calls == ["bank", "prime"] and report["cache_bank"]["bank"] == "restored"
    monkeypatch.delenv(banks.ENV_ENABLE)
    calls.clear()
    report = warmup.warm_up(setup.settings, home=setup.home, chat_id="c001")
    assert calls == ["prime"] and "cache_bank" not in report
