"""Start thinking while I type (star/prefill_warm.py): the draft's start goes to the model server ahead of Enter.

It must send exactly the start the real turn will have (same model, same slot, the owner's words as the end of
the text, cut before the template's closing tokens), stay off when switched off and off cloud providers, keep a
small budget while the server answers someone else, use the PC's model when the turn would, keep only the
newest draft, and leave no trace.
"""
import asyncio
import json
import threading
import time

import httpx
import pytest

import star.desktop_core as core
import star.prefill_warm as prefill
from star import providers
from star.desktop_core import Settings, run_task
from star.prefill_warm import DraftWarmer, warm_draft
from star.providers import PROVIDERS, remember_server_limits

from test_warmup import desk, footprint, lan_settings  # noqa: F401  (desk is a fixture)

KEY = "sk-star-test-0123456789"  # star:allow (test fake)


def on(settings):
    settings.prefill_while_typing = True
    return settings


def _text(message):
    content = message["content"]
    return content if isinstance(content, str) else "".join(part.get("text", "") for part in content)


class FakeServer:
    """llama.cpp's /apply-template (a ChatML-like template) and /v1/completions, recording every call."""

    def __init__(self, render=None):
        self.calls, self.render = [], render

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"host": f"{request.url.host}:{request.url.port}", "path": request.url.path,
                           "auth": request.headers.get("authorization"), "body": body})
        if request.url.path == "/apply-template":
            prompt = self.render(body) if self.render else "".join(
                f"<|im_start|>{m['role']}\n{_text(m)}<|im_end|>\n" for m in body["messages"]) + "<|im_start|>assistant\n"
            return httpx.Response(200, json={"prompt": prompt})
        if request.url.path.endswith("/completions"):
            return httpx.Response(200, json={"choices": [{"text": "x"}], "timings": {"prompt_n": 12, "cache_n": 400}})
        raise AssertionError(f"unexpected {request.url.path}")

    def sent(self):
        return [call for call in self.calls if call["path"].endswith("/completions")]


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(prefill, "_TRANSPORT", httpx.MockTransport(fake.handle))
    return fake


def test_off_by_default_and_then_nothing_is_sent(desk, server):
    assert Settings().prefill_while_typing is False
    report = warm_draft(desk.settings, desk.home, desk.chat, "How do I make a door open when touched?")
    assert report["skipped"] == "off" and server.calls == []


def test_draft_is_the_exact_start_of_the_real_turn(desk, server):
    settings = on(desk.settings)
    draft = "And how do I make the welded parts"
    report = warm_draft(settings, desk.home, desk.chat, draft, mode="fast")
    assert report["primed"] is True and report["on_pc"] is False and report["with_tools"] is False
    assert report["prompt_tokens_read"] == 12 and report["prompt_tokens_cached"] == 400
    template, sent = server.calls[0]["body"], server.sent()[0]["body"]
    assert "tools" not in template and template["messages"][-1]["content"] == [{"type": "text", "text": draft}]
    # The raw text ends with the owner's words: no closing template tokens, so the server's
    # end-of-prompt checkpoint lands inside what the real turn will send.
    assert sent["prompt"].endswith("<|im_start|>user\n" + draft) and sent["max_tokens"] == 1
    assert sent["model"] == template["model"] and sent["cache_prompt"] is True
    # Enter: the owner finished the sentence; the real turn starts with the same messages.
    final = draft + " spin slowly?"
    desk.chats.add("STAR", "user", final, chat_id=desk.chat)
    run_task(settings, final, mode="fast", chat_id=desk.chat)
    real = desk.models.requests[0]
    assert json.dumps(real["messages"][:-1]) == json.dumps(template["messages"][:-1])
    assert real["model"] == sent["model"]
    assert real["extra_body"]["chat_template_kwargs"] == template["chat_template_kwargs"]
    assert real["extra_body"]["cache_prompt"] is True
    assert real["messages"][-1]["content"][0]["text"].startswith(draft)


def test_a_template_that_does_not_show_the_draft_sends_nothing(desk, monkeypatch):
    fake = FakeServer(render=lambda body: "something else entirely")
    monkeypatch.setattr(prefill, "_TRANSPORT", httpx.MockTransport(fake.handle))
    report = warm_draft(on(desk.settings), desk.home, desk.chat, "How do I anchor every part at once?")
    assert report["skipped"] == "template" and fake.sent() == []


def test_same_slot_as_the_turn_on_star_server(desk, server, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = on(lan_settings())
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    asked = []

    async def idle(settings, model, *, conversation=""):
        asked.append(model)
        return frozenset()
    report = warm_draft(settings, desk.home, desk.chat, "Write a Luau script that spins a part", probe=idle)
    assert report["primed"] is True and asked == ["star-fast"]
    sent = server.sent()[0]
    assert sent["host"] == "192.168.50.20:8080" and sent["path"] == "/v1/completions"  # star:allow (test address)
    assert server.calls[0]["path"] == "/apply-template" and sent["auth"] == f"Bearer {KEY}"
    turn = core.llama_request_fields(settings, conversation=core.memory_scope_for(settings, desk.chat),
                                     model="star-fast")
    assert sent["body"]["id_slot"] == turn["id_slot"] in (0, 1)
    assert KEY not in json.dumps(report)


def test_small_budget_while_the_server_answers_someone_else(desk, server, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = on(lan_settings())
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    scope = core.memory_scope_for(settings, desk.chat)
    own = core.llama_request_fields(settings, conversation=scope, model="star-fast", prime=True)["id_slot"]

    def answering(slots):
        async def probe(settings, model, *, conversation=""):
            # What look_for_busy_slots leaves for the next slot choice, as the real probe does.
            providers._BUSY_SLOTS[providers._instance(settings, model)] = (time.monotonic(), frozenset(slots))
            return frozenset(slots)
        return probe
    # Both slots generating (night school, another client): nothing is sent, it would only wait.
    report = warm_draft(settings, desk.home, desk.chat, "Write a Luau script that spins a part",
                        probe=answering({0, 1}))
    assert report["skipped"] == "server_busy" and server.calls == []
    # One slot busy: a long draft is not sent; a short one goes to the idle slot, where the turn will go.
    long = "Explain this script: " + "local x = 1 " * 200
    assert warm_draft(settings, desk.home, desk.chat, long, probe=answering({own}))["skipped"] == "server_busy"
    report = warm_draft(settings, desk.home, desk.chat, "Write a Luau script that spins a part",
                        probe=answering({own}))
    assert report["primed"] is True and report["server_busy"] is True
    moved = server.sent()[-1]["body"]["id_slot"]
    assert moved == 1 - own
    assert core.llama_request_fields(settings, conversation=scope, model="star-fast")["id_slot"] == moved


def test_never_a_cloud_provider_and_never_a_tiny_draft(desk, monkeypatch):
    def forbidden(request):
        raise AssertionError("a cloud provider must not be contacted")
    monkeypatch.setattr(prefill, "_TRANSPORT", httpx.MockTransport(forbidden))
    for name in PROVIDERS:
        monkeypatch.setenv(PROVIDERS[name].env_var, "key-0123456789")
        settings = on(Settings(provider=name, model=PROVIDERS[name].suggested_model))
        assert warm_draft(settings, desk.home, desk.chat, "How do I make a door open?")["skipped"] == "cloud"
    assert warm_draft(on(Settings(model="qwen-test")), desk.home, desk.chat, "hi there")["skipped"] == "short"


def test_a_tool_turn_with_no_known_tool_list_is_not_warmed(desk, server):
    # A plain prompt would replace the tool prompt the slot holds, so nothing is sent.
    report = warm_draft(on(desk.settings), desk.home, desk.chat, "Plan and build an obby in my game", mode="agent")
    assert report["skipped"] == "tools_unknown" and server.calls == []


def test_leaves_no_trace(desk, server):
    before = footprint(desk.home)
    assert warm_draft(on(desk.settings), desk.home, desk.chat, "How do I anchor every part at once?")["primed"]
    assert footprint(desk.home) == before


def test_goes_to_the_pc_when_the_turn_would_and_never_holds_it(desk, server, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = on(lan_settings())
    settings.use_my_gpu = True
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    ended = []
    monkeypatch.setattr(prefill.gpu_helper.HELPER, "warm_begin", lambda: "http://127.0.0.1:5999/v1")
    monkeypatch.setattr(prefill.gpu_helper.HELPER, "warm_end", lambda: ended.append(1))

    async def never(*_, **__):
        raise AssertionError("the PC is not the server: no slot question")
    report = warm_draft(settings, desk.home, desk.chat, "Write a Luau script that spins a part", probe=never)
    assert report["primed"] is True and report["on_pc"] is True
    assert {call["host"] for call in server.calls} == {"127.0.0.1:5999"}
    assert [call["path"] for call in server.calls] == ["/apply-template", "/v1/completions"]
    body = server.sent()[0]["body"]
    assert body["model"] == "star-fast" and "id_slot" not in body and server.sent()[0]["auth"] is None
    assert ended == [1]                   # the card is STAR's own work only while the draft runs
    # Not loaded or answering the real turn: the draft goes to the server instead (and nothing is started).
    monkeypatch.setattr(prefill.gpu_helper.HELPER, "warm_begin", lambda: None)

    async def idle(*_, **__):
        return frozenset()
    assert warm_draft(settings, desk.home, desk.chat, "Write a Luau script that spins a part",
                      probe=idle)["on_pc"] is False
    assert server.sent()[-1]["host"] == "192.168.50.20:8080"  # star:allow (test address)


def test_pc_warm_up_is_not_a_lease_and_keeps_the_watchdog_calm():
    readings = []
    helper = prefill.gpu_helper.GpuHelper(watchdog=False, gpu=lambda: readings[-1], ram=lambda: 20000,
                                          image_engine=lambda port: False)
    assert helper.warm_begin() is None and helper.want_start is False      # never starts a model
    helper.enabled, helper.state, helper.base = True, "ready", "http://127.0.0.1:5999/v1"
    helper._alive = lambda: True
    helper.process = type("Running", (), {"poll": lambda self: None})()
    helper.last_used = helper._clock()
    assert helper.warm_begin() == "http://127.0.0.1:5999/v1" and helper.in_flight == 0
    assert helper.lease() == "http://127.0.0.1:5999/v1"                     # the real turn still gets the PC
    helper.finish(ok=True)
    # The card is hot with STAR's own draft: two hot samples do not stop the model.
    readings.append(prefill.gpu_helper.GpuReading(utilization=99, used_mib=6000, total_mib=8192))
    helper.tick(), helper.tick()
    assert helper.state == "ready"
    helper.warm_end()
    helper.tick(), helper.tick()                                            # now it is another program
    assert helper.state == "busy"
    helper.in_flight = 1
    helper.state = "ready"
    assert helper.warm_begin() is None                                      # the real turn is on the PC


def test_a_cancelled_draft_keeps_its_slot_for_the_turn(desk, monkeypatch):
    # Enter cancels the draft; the server still finishes the batch it reads, so for a short while the chat's
    # slot looks busy. It is this app's own warm-up: the turn must stay there and reuse it.
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = on(lan_settings())
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    started, cancel = threading.Event(), threading.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apply-template":
            body = json.loads(request.content)
            return httpx.Response(200, json={"prompt": "<|im_start|>user\n" + _text(body["messages"][-1])})
        started.set()
        await asyncio.sleep(5)
        return httpx.Response(200, json={})
    monkeypatch.setattr(prefill, "_TRANSPORT", httpx.MockTransport(slow))

    async def idle(*_, **__):
        return frozenset()
    worker = threading.Thread(target=lambda: warm_draft(settings, desk.home, desk.chat,
                                                        "Write a Luau script that spins a part",
                                                        probe=idle, cancel_event=cancel))
    worker.start()
    assert started.wait(5)
    cancel.set()
    worker.join(5)
    scope = core.memory_scope_for(settings, desk.chat)
    slot = core.llama_request_fields(settings, conversation=scope, model="star-fast", prime=True)["id_slot"]
    assert providers._own_warm(providers._instance(settings, "star-fast"), slot)


def test_the_turn_stays_on_its_slot_while_its_own_warm_up_is_still_reading(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = lan_settings()
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    scope = "STAR::chat::own-warm"
    slot = providers.llama_request_fields(settings, conversation=scope, model="star-fast", prime=True)["id_slot"]
    report = [{"id": slot, "is_processing": True}, {"id": 1 - slot, "is_processing": False}]
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT",
                        httpx.MockTransport(lambda _: httpx.Response(200, json=report)))
    mark = providers.own_warm_started(settings, "star-fast", slot)
    providers.own_warm_ended(mark, cancelled=True)
    assert asyncio.run(providers.look_for_busy_slots(settings, "star-fast", conversation=scope)) == frozenset()
    assert providers.llama_request_fields(settings, conversation=scope, model="star-fast")["id_slot"] == slot
    # Once the grace is over a busy slot is someone else's again, and the turn moves (issue 118).
    providers._OWN_WARMS[mark] = time.monotonic() - 1
    assert asyncio.run(providers.look_for_busy_slots(settings, "star-fast", conversation=scope)) == {slot}
    assert providers.llama_request_fields(settings, conversation=scope, model="star-fast")["id_slot"] == 1 - slot
    # A warm-up that finished normally leaves no mark.
    providers.own_warm_ended(providers.own_warm_started(settings, "star-fast", 1 - slot), cancelled=False)
    assert not providers._own_warm(providers._instance(settings, "star-fast"), 1 - slot)


def test_draft_warmer_keeps_only_the_newest_draft_and_stops_on_a_real_request():
    started, release, seen = threading.Event(), threading.Event(), []

    def slow(settings, home, chat_id, text, *, mode, research, cancel_event):
        seen.append((text, mode, cancel_event))
        started.set()
        release.wait(5)
        return {"primed": not cancel_event.is_set()}
    warmer = DraftWarmer(run=slow)
    load = lambda: ("settings", "home", "chat")
    warmer.submit(load, "How do I make", mode="fast")
    assert started.wait(5)
    for text in ("How do I make a door", "How do I make a door open", "How do I make a door open on touch"):
        warmer.submit(load, text, mode="fast")          # while the first runs: only the newest is kept
    started.clear()
    release.set()
    assert started.wait(5)
    warmer.thread and warmer.thread.join(5)
    assert [text for text, _, _ in seen] == ["How do I make", "How do I make a door open on touch"]
    # A real request cancels the running one and drops what was waiting; a later draft runs again.
    release.clear(), started.clear()
    warmer.submit(load, "Another question for STAR")
    assert started.wait(5)
    warmer.submit(load, "Another question for STAR, longer")
    warmer.cancel()
    assert seen[-1][2].is_set()
    release.set()
    warmer.thread and warmer.thread.join(5)
    assert seen[-1][0] == "Another question for STAR"
    warmer.submit(load, "After the answer, a new draft")
    warmer.thread and warmer.thread.join(5)
    assert seen[-1][0] == "After the answer, a new draft" and not seen[-1][2].is_set()


def test_draft_warmer_swallows_failures():
    def broken(*_, **__):
        raise RuntimeError("boom")
    warmer = DraftWarmer(run=broken)
    warmer.submit(lambda: ("s", "h", "c"), "How do I make a door open?")
    warmer.thread and warmer.thread.join(5)
    assert warmer.last == {"primed": False, "error": "RuntimeError"}


def test_host_allows_the_action_and_the_setting():
    import star.react_shell as shell
    assert "warmDraft" in shell.ALLOWED_ACTIONS and "warmDraft" not in shell.WARM_UP_STOPPERS
    assert "prefill_while_typing" in shell.PERMITTED_SETTINGS
    assert "sendMessage" in shell.WARM_UP_STOPPERS


def test_chunk_ends_bound_each_step_and_prefer_a_space():
    text = ("word " * 300).strip()                       # 1,499 characters
    ends = prefill.chunk_ends(text, 0, 400)
    assert ends[-1] == len(text) and ends == sorted(ends)
    steps = [b - a for a, b in zip([0] + ends, ends)]
    assert max(steps) <= 400 and all(text[end - 1] == " " for end in ends[:-1])
    assert prefill.chunk_ends(text, len(text) - 10, 400) == [len(text)]
    assert prefill.chunk_ends("x" * 900, 0, 400) == [400, 800, 900]   # no space: a hard cut
    assert prefill.chunk_ends("short", 0, 400) == [5]


def test_a_long_paste_goes_in_chunks_and_the_next_draft_sends_only_the_rest(desk, server):
    settings = on(desk.settings)
    script = "local part = workspace.Part\n" + "part.Size = Vector3.new(4, 1, 2) -- size\n" * 30
    draft = "Fix this script so the part spins:\n" + script      # ~1,300 characters
    report = warm_draft(settings, desk.home, desk.chat, draft, mode="fast")
    sent = [call["body"]["prompt"] for call in server.sent()]
    assert report["primed"] is True and report["chunks"] == len(sent) >= 4
    assert sent[-1].endswith("<|im_start|>user\n" + draft)
    # Each request extends the one before by at most CHUNK_CHARS: the server is never far from a real request.
    assert all(b.startswith(a) and 0 < len(b) - len(a) <= prefill.CHUNK_CHARS for a, b in zip(sent, sent[1:]))
    assert report["prompt_tokens_read"] == 12 * len(sent)
    # The owner adds a few words: one request, from where the paste ended.
    server.calls.clear()
    report = warm_draft(settings, desk.home, desk.chat, draft + "Also make it red.", mode="fast")
    assert len(server.sent()) == 1 and "chunks" not in report


def test_a_cancel_between_chunks_sends_no_more(desk, monkeypatch):
    settings = on(desk.settings)
    cancel, sent = threading.Event(), []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "<|im_start|>user\n" + _text(body["messages"][-1])})
        sent.append(body["prompt"])
        cancel.set()                                      # Enter arrives while the first chunk is read
        await asyncio.sleep(0.3)
        return httpx.Response(200, json={"timings": {"prompt_n": 100}})
    monkeypatch.setattr(prefill, "_TRANSPORT", httpx.MockTransport(handler))
    report = warm_draft(settings, desk.home, desk.chat, "Explain this:\n" + "x = x + 1\n" * 200, mode="fast",
                        cancel_event=cancel)
    assert report.get("cancelled") is True and len(sent) == 1


def test_chunks_stop_when_another_client_starts_generating(desk, server, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = on(lan_settings())
    remember_server_limits(settings.server_endpoint, "star-fast", 32768, 2)
    asked = []

    async def probe(settings, model, *, conversation=""):
        asked.append(model)
        return frozenset() if len(asked) == 1 else frozenset({1})   # idle at the start, then a client arrives
    draft = "Fix this:\n" + "part.Anchored = true -- keep it still\n" * 40
    report = warm_draft(settings, desk.home, desk.chat, draft, probe=probe)
    assert report["primed"] is True and report["yielded"] is True
    assert len(server.sent()) == 1 and len(asked) == 2
