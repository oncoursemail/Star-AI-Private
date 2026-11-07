"""Time to first token: the request layout a llama.cpp server can cache.

Each request must start with the same bytes as the one before it (rules, stable
memory, then earlier turns in append-only order); everything that changes per
turn goes last; the llama.cpp cache fields never reach a cloud provider; and a
tool-using turn streams like a plain one.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import star.agent as agent
import star.desktop_core as core
from star.agent import FAST_RULES, RULES, execute, system_prefix, volatile_context
from star.context_layout import (CONTEXT_CLOSE, CONTEXT_OPEN, NO_REPLY, TRIM_BLOCK, conversation_window,
                                 drop_oldest_turns, exchanges, history_chars, owner_words)
from star.desktop_core import Conversations, Settings, chat_history, run_task
from star.providers import PROVIDERS, llama_request_fields, remember_server_limits


def reply(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


class Models:
    """Records every request as it was sent (a snapshot, not a live reference)."""
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer(kwargs) if callable(answer) else answer


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def text_of(message) -> str:
    content = message.get("content") or ""
    return content if isinstance(content, str) else "".join(part.get("text", "") for part in content)


def rendered(messages) -> str:
    """ChatML as a Qwen template renders it; what the server tokenises and caches."""
    return "".join(f"<|im_start|>{m['role']}\n{text_of(m).strip()}<|im_end|>\n" for m in messages)


def schema_tool(name):
    return {"name": name, "description": "fake", "inputSchema": {
        "type": "object", "properties": {"studio_id": {"type": "string"}}, "required": ["studio_id"]}}


class Studio:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(model_dump=lambda **_: {"content": [{"type": "text", "text": "seen"}], "isError": False})


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A private app-data folder and a fake model client behind run_task."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    models = Models()
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    chats = Conversations(home / "conversations.sqlite3")
    chat = chats.new_chat("STAR")
    settings = Settings(model="qwen-test")

    def turn(text, answer, **options):
        """What the desktop bridge does for one message: save it, answer it, save the answer."""
        chats.add("STAR", "user", text, chat_id=chat)
        models.responses.append(reply(answer))
        result = run_task(options.pop("settings", settings), text, chat_id=chat, **{"mode": "fast", **options})
        chats.add("STAR", "assistant", result, chat_id=chat)
        return models.requests[-1]

    yield SimpleNamespace(models=models, home=home, chats=chats, chat=chat, settings=settings, turn=turn)
    chats.close()


# ------------------------------------------------------------------ layout

def test_request_is_system_then_history_then_the_new_turn_with_context_last():
    async def run():
        models = Models([reply("ok")])
        history = [{"role": "user", "content": "first question"}, {"role": "assistant", "content": "first answer"}]
        await execute(client=Client(models), model="m", prompt="second question", image_paths=[],
                      project_memory="checkpoint text", history=history, mode="fast", today="2026-10-10",
                      turn_sections=[("REVIEWED KNOWLEDGE", "the lobby uses gold accents")])
        messages = models.requests[0]["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
        assert messages[1:3] == history
        system, final = messages[0]["content"], text_of(messages[-1])
        # Stable things first ...
        assert system.startswith(FAST_RULES) and "checkpoint text" in system
        # ... and nothing per-turn in the system message.
        for volatile in ("gold accents", "2026-10-10", "Selected studio_id", "Mode:", "second question"):
            assert volatile not in system
        # The user's words come first, the context block after them.
        assert final.startswith("second question\n\n" + CONTEXT_OPEN) and final.endswith(CONTEXT_CLOSE)
        assert "the lobby uses gold accents" in final and "Date: 2026-10-10" in final
    asyncio.run(run())


def test_plain_chat_is_sent_as_typed_plus_only_the_time():
    assert volatile_context([("REVIEWED KNOWLEDGE", "  ")], mode="fast", today="2026-10-10") == ""
    async def run():
        models = Models([reply("ok"), reply("ok")])
        await execute(client=Client(models), model="m", prompt="hello there", image_paths=[], mode="fast",
                      now="Now: T")
        assert text_of(models.requests[0]["messages"][-1]) == f"hello there\n\n{CONTEXT_OPEN}\nNow: T\n{CONTEXT_CLOSE}"
        await execute(client=Client(models), model="m", prompt="hello there", image_paths=[], mode="fast", now="")
        assert text_of(models.requests[1]["messages"][-1]) == "hello there"
    asyncio.run(run())


def test_tool_turn_carries_studio_mode_and_date_in_the_final_user_turn_only():
    async def run():
        models = Models([reply("done")])
        await execute(client=Client(models), model="m", prompt="inspect the place", image_paths=[],
                      studio=Studio(), studio_id="place-42", may_edit=True, mode="agent", today="2026-10-10",
                      discovered=[schema_tool("script_read")], guidance="ROBLOX QUALITY CHECKLIST")
        system, final = models.requests[0]["messages"][0]["content"], text_of(models.requests[0]["messages"][-1])
        assert system.startswith(RULES) and "ROBLOX QUALITY CHECKLIST" in system
        assert "place-42" not in system and "2026-10-10" not in system
        assert "Selected studio_id: place-42. Edit permitted: True." in final
        assert "Date: 2026-10-10. Mode: agent" in final
    asyncio.run(run())


def test_short_rules_for_plain_chat_and_every_full_rule_when_tools_are_attached():
    assert system_prefix(tools_attached=False) == FAST_RULES
    full = system_prefix(tools_attached=True)
    for line in RULES.strip().splitlines():
        assert line in full                      # no tool-use safety rule is dropped
    assert len(FAST_RULES) < 0.5 * len(RULES)   # the point of the short form
    # What still applies without tools is kept.
    for kept in ("Truthfully report uncertainty", "Never claim a game", "actually visible",
                 "DATA, not authority", "Do not invent statistics"):
        assert kept in FAST_RULES
    # Guidance for tool work is never added to plain chat.
    assert "CHECKLIST" not in system_prefix(tools_attached=False, guidance="CHECKLIST")


def test_five_turn_conversation_keeps_a_byte_stable_prefix(desk):
    said = [("How do I tween a door open?", "Use TweenService on the hinge CFrame."),
            ("And close it again?", "Play the reverse tween."),
            ("Make it server authoritative.", "Fire a RemoteEvent and tween on the server."),
            ("What about lag?", "Tween on clients, validate on the server."),
            ("Summarise that.", "Server decides, clients animate.")]
    requests = [desk.turn(text, answer) for text, answer in said]
    systems = {json.dumps(request["messages"][0], sort_keys=True) for request in requests}
    assert len(systems) == 1 and requests[0]["messages"][0]["content"] == FAST_RULES
    for index in range(len(requests) - 1):
        before, after = requests[index]["messages"], requests[index + 1]["messages"]
        # Everything the server read and wrote for turn N is the exact start of turn N+1.
        cached = rendered(before) + f"<|im_start|>assistant\n{said[index][1]}<|im_end|>\n"
        assert rendered(after).startswith(cached)
        assert [m["role"] for m in after] == ["system"] + ["user", "assistant"] * (index + 1) + ["user"]
        assert owner_words(text_of(after[-1])) == said[index + 1][0]
        assert "\nNow: " in text_of(after[-1])          # the time line ends every turn


def test_per_turn_notes_reach_only_their_own_turn(desk, monkeypatch):
    from star.knowledge import KnowledgeStore
    note = SimpleNamespace(kind="decision", revision=1, source="user", text="Doors are painted teal.")
    monkeypatch.setattr(KnowledgeStore, "find_contextual",
                        lambda self, project, prompt, limit=8: [note] if "door" in prompt else [])
    first = desk.turn("What colour is the door?", "Teal.")["messages"]
    second = desk.turn("Thanks.", "You are welcome.")["messages"]
    assert "Doors are painted teal." in text_of(first[-1]) and "Doors are painted teal." not in first[0]["content"]
    assert "Doors are painted teal." not in json.dumps(second)
    # History replays the user's own words (and the time they were sent); the start of the request
    # is still shared up to them.
    assert second[1]["role"] == "user" and owner_words(second[1]["content"]) == "What colour is the door?"
    assert "Doors are painted teal." not in second[1]["content"]
    assert rendered(second).startswith(rendered(first[:-1]) + "<|im_start|>user\nWhat colour is the door?")


@pytest.mark.parametrize("status", ["failed", "cancelled", None], ids=["failed", "cancelled", "interrupted"])
def test_history_drops_unanswered_turns_and_preserves_failure_records_in_storage(desk, status):
    first = desk.turn("first", "one")["messages"]
    failed = desk.chats.add("STAR", "user", "this one failed", chat_id=desk.chat)
    if status is not None:
        desk.chats.add_terminal("STAR", desk.chat, failed, status, "SECRET-FAILURE-TEXT")
    originals = desk.chats.raw_history_records("STAR", desk.chat)
    messages = desk.turn("second", "two")["messages"]
    # The exclusion rule drops the whole orphan, not just its failure event.
    assert [owner_words(text_of(m)) for m in messages[1:]] == ["first", "one", "second"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    for excluded in ("this one failed", NO_REPLY, "SECRET-FAILURE-TEXT"):
        assert excluded not in json.dumps(messages)
    assert rendered(messages).startswith(rendered(first) + "<|im_start|>assistant\none<|im_end|>\n")
    assert desk.chats.raw_history_records("STAR", desk.chat)[:len(originals)] == originals


# ------------------------------------------------------------------ trimming

def conversation(count):
    rows = []
    for number in range(count):
        rows += [("user", f"question {number}"), ("assistant", f"answer {number}")]
    return rows


def test_history_window_only_moves_in_whole_blocks():
    budget, moves, previous, sizes = 2000, 0, [], []
    for turns in range(0, 80):
        rows = conversation(turns) + [("user", "the message being answered now")]
        window = conversation_window(rows, budget_chars=budget)
        assert history_chars(window) <= budget
        sizes.append(history_chars(window))
        if window[:len(previous)] == previous:
            assert len(window) - len(previous) in (0, 2)     # append-only: just the newest exchange
        else:
            moves += 1                                       # the start moved forward, never back
            assert window[-2:] == [{"role": "user", "content": f"question {turns - 1}"},
                                   {"role": "assistant", "content": f"answer {turns - 1}"}]
            dropped = len(previous) + 2 - len(window)
            assert dropped >= 20 and window[:-2] == previous[dropped:]
        previous = window
    # About 1800 characters of talk in 2000-character windows: the start moved once per
    # half budget, not once per turn, and the window never fell below about half of it.
    assert moves == sum(len(text) for _, text in conversation(79)) // (budget // 2) - 1
    assert min(sizes[60:]) > budget * 0.4


def test_history_window_always_keeps_the_newest_exchange_within_budget():
    rows = [(role, text + " " + "x" * 5000) for role, text in conversation(12)]
    for count in range(2, 25, 2):
        window = conversation_window(rows[:count], budget_chars=3000)
        assert 2 <= len(window) and history_chars(window) <= 3000
        assert window[-1]["content"].startswith(f"answer {count // 2 - 1} ")
        assert all(len(m["content"]) <= 3000 // 4 for m in window)   # long messages are shortened
    assert conversation_window(rows, budget_chars=0) == []
    # A window never starts with an answer and never ends with an unanswered question.
    assert [m["role"] for m in exchanges(rows[1:] + [("user", "pending")])][:2] == ["user", "assistant"]
    assert exchanges(rows[1:] + [("user", "pending")])[-1]["role"] == "assistant"


def test_over_budget_task_drops_oldest_turns_and_keeps_the_prefix(monkeypatch):
    async def never(*_, **__):
        raise AssertionError("trimming earlier turns must not cost a summarising model call")
    monkeypatch.setattr(agent, "compact", never)
    history = [{"role": role, "content": text + " " + "y" * 300} for role, text in conversation(6)]

    async def run(budget):
        models = Models([reply("ok")])
        await execute(client=Client(models), model="m", prompt="newest question", image_paths=[],
                      project_memory="stable checkpoint", history=history, context_chars=budget)
        return models.requests[0]["messages"]
    whole, trimmed = asyncio.run(run(10 ** 6)), asyncio.run(run(3200))
    assert trimmed[0] == whole[0]                                # the cached start survives
    dropped = len(whole) - len(trimmed)
    assert dropped > 0 and dropped % TRIM_BLOCK == 0
    assert trimmed[1:] == whole[1 + dropped:]                    # oldest first, the rest untouched
    assert trimmed[1]["role"] == "user" and owner_words(text_of(trimmed[-1])) == "newest question"


def test_drop_oldest_turns_never_touches_the_request_being_answered():
    messages = [{"role": "system", "content": "s"}, *[{"role": r, "content": t} for r, t in conversation(3)],
                {"role": "user", "content": "now"}, {"role": "assistant", "content": "tool call"}]
    kept, anchor = drop_oldest_turns(messages, 7, 0, lambda m: sum(len(x["content"]) for x in m))
    assert kept == [messages[0], *messages[7:]] and anchor == 1


# ------------------------------------------------------------------ provider fields

def test_cloud_providers_never_get_llama_fields(monkeypatch, desk):
    for name in PROVIDERS:
        assert llama_request_fields(Settings(provider=name, model="m"), conversation="c", tools=True) == {}
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_0123456789")
    request = desk.turn("hello", "hi", settings=Settings(provider="groq", model="openai/gpt-oss-20b"))
    assert "extra_body" not in request
    assert not {"cache_prompt", "id_slot", "chat_template_kwargs"} & set(request)


def test_own_llama_servers_get_cache_fields_and_a_steady_slot(desk):
    local = llama_request_fields(Settings(model="m"), conversation="STAR::chat::a")
    assert local == {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}}
    assert desk.turn("hello", "hi")["extra_body"] == local

    lan = Settings(provider="star_server", server_endpoint="http://192.168.50.20:8080/v1", model="star-fast")
    assert "id_slot" not in llama_request_fields(lan, conversation="a")      # slot count not known yet
    remember_server_limits("http://192.168.50.20:8080/v1", "star-fast", 32768, 2)
    chat = llama_request_fields(lan, conversation="STAR::chat::a")
    tools = llama_request_fields(lan, conversation="STAR::chat::a", tools=True)
    assert chat["cache_prompt"] is True and chat["id_slot"] in (0, 1)
    assert chat == llama_request_fields(lan, conversation="STAR::chat::a")   # one conversation, one slot
    # One conversation, one slot per model: the tool prompt shares it. Background work names
    # no slot (tests/test_model_routing.py covers the slot rules).
    assert tools["id_slot"] == chat["id_slot"]
    assert llama_request_fields(lan, conversation="STAR::chat::a", background=True) == local
    remember_server_limits("http://192.168.50.20:8080/v1", "star-fast", 32768, 1)
    assert "id_slot" not in llama_request_fields(lan, conversation="a")


def test_a_server_that_refuses_the_cache_fields_is_asked_again_without_them():
    class Refused(Exception):
        status_code = 400

    async def run():
        models = Models([Refused("unknown field"), reply("ok")])
        answer, _, _ = await execute(client=Client(models), model="m", prompt="hi", image_paths=[],
                                     request_extras=lambda tools: {"cache_prompt": True, "tools_lane": tools})
        assert answer == "ok"
        assert models.requests[0]["extra_body"] == {"cache_prompt": True, "tools_lane": False}
        assert "extra_body" not in models.requests[1]
        assert models.requests[1]["messages"] == models.requests[0]["messages"]
    asyncio.run(run())


# ------------------------------------------------------------------ streaming with tools

def chunk(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content="private"))])


def fragment(index, call_id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def streaming(*chunks):
    async def stream():
        for item in chunks:
            yield item
    return lambda kwargs: stream()


def test_tool_using_turn_streams_text_and_rebuilds_the_tool_call():
    async def run():
        models = Models([
            streaming(chunk("Let me read "), chunk("the script."),
                      chunk(tool_calls=[fragment(0, "call-7", "script_read", "")]),
                      chunk(tool_calls=[fragment(0, arguments='{"studio_id":')]),
                      chunk(tool_calls=[fragment(0, arguments=' "sandbox"}')]),
                      SimpleNamespace(choices=[])),
            streaming(chunk("It prints "), chunk("hello.")),
        ])
        events, studio = [], Studio()
        answer, messages, _ = await execute(
            client=Client(models), model="m", prompt="inspect the script", image_paths=[], studio=studio,
            studio_id="sandbox", discovered=[schema_tool("script_read")], stream_tokens=True, on_event=events.append)
        assert answer == "It prints hello."
        assert all(request["stream"] is True and request["tools"] for request in models.requests)
        assert studio.calls == [("script_read", {"studio_id": "sandbox"})]
        # The streamed fragments became one well-formed call that the next request replays.
        replay = models.requests[1]["messages"]
        assert replay[-2]["tool_calls"] == [{"id": "call-7", "type": "function", "function": {
            "name": "script_read", "arguments": '{"studio_id": "sandbox"}'}}]
        assert replay[-2]["content"] == "Let me read the script."
        assert replay[-1]["role"] == "tool" and replay[-1]["tool_call_id"] == "call-7"
        # Progress in order: the turn starts, its text streams, the tool runs, the answer streams.
        kinds = [e["event"] for e in events]
        assert kinds.index("model_turn") < kinds.index("model_responding") < kinds.index("assistant_delta")
        assert kinds.index("assistant_delta") < kinds.index("tool_requested") < kinds.index("tool_started")
        assert events[kinds.index("tool_requested")] == {"event": "tool_requested"}   # no name before authorization
        assert kinds.count("model_responding") == 2 and kinds.count("tool_requested") == 1
        assert kinds.index("tool_finished") < len(kinds) - 1 - kinds[::-1].index("assistant_delta")
        shown = "".join(e["text"] for e in events if e["event"] == "assistant_delta")
        assert shown == "Let me read the script.\n\nIt prints hello." and "private" not in shown
        assert messages[-1] == {"role": "assistant", "content": "It prints hello."}
    asyncio.run(run())


def test_streamed_tool_calls_without_index_or_id_still_work():
    async def run():
        models = Models([
            streaming(chunk(tool_calls=[fragment(None, None, "script_read", '{"studio_id": "sandbox"}')])),
            streaming(chunk("Done.")),
        ])
        studio = Studio()
        answer, messages, _ = await execute(
            client=Client(models), model="m", prompt="inspect", image_paths=[], studio=studio,
            studio_id="sandbox", discovered=[schema_tool("script_read")], stream_tokens=True)
        assert answer == "Done." and len(studio.calls) == 1
        call_id = models.requests[1]["messages"][-2]["tool_calls"][0]["id"]
        assert call_id and models.requests[1]["messages"][-1]["tool_call_id"] == call_id
    asyncio.run(run())


def test_stream_mode_refused_with_tools_falls_back_to_one_complete_reply():
    class Refused(Exception):
        status_code = 501

    async def run():
        models = Models([Refused("no streaming"), reply("plain answer")])
        answer, _, _ = await execute(client=Client(models), model="m", prompt="inspect", image_paths=[],
                                     studio=Studio(), studio_id="sandbox",
                                     discovered=[schema_tool("script_read")], stream_tokens=True)
        assert answer == "plain answer" and "stream" not in models.requests[1]
    asyncio.run(run())


def test_chat_history_is_the_same_for_a_turn_and_for_the_warm_up(desk):
    desk.turn("one", "first answer")
    idle, _ = chat_history(desk.settings, desk.home, desk.chat)            # nothing pending
    desk.chats.add("STAR", "user", "two", chat_id=desk.chat)               # the UI saved the new message
    busy, rows = chat_history(desk.settings, desk.home, desk.chat)
    assert idle == busy
    assert [(m["role"], owner_words(m["content"])) for m in busy] == [("user", "one"), ("assistant", "first answer")]
    assert "\nNow: " in busy[0]["content"]       # replayed with the time it was sent
    assert rows[-1][:2] == ("user", "two")


def test_studio_tools_come_after_the_tools_every_turn_has():
    """Qwen templates render tools before the system text: the stable ones must lead."""
    async def run():
        models = Models([reply("ok")])
        await execute(client=Client(models), model="m", prompt="inspect", image_paths=[], studio=Studio(),
                      studio_id="sandbox", discovered=[schema_tool("script_read")],
                      subagents_enabled=True, web_search_enabled=True)
        names = [tool["function"]["name"] for tool in models.requests[0]["tools"]]
        assert names == ["star_delegate", "star_web_search", "star_web_fetch", "script_read"]
    asyncio.run(run())


def test_early_progress_events_have_wording_and_reveal_nothing():
    from star.react_shell import sanitize_event
    assert sanitize_event({"event": "model_responding"}) == {"phase": "The model is writing"}
    assert sanitize_event({"event": "tool_requested", "tool": "execute_luau", "arguments": "secret"}) == {
        "phase": "Preparing a tool request"}


# ------------------------------------------------------------------ a prompt that does not fit is not resent

class ContextRefused(Exception):
    status_code = 400


@pytest.mark.parametrize("message", [
    "the request exceeds the available context size, try increasing it",          # llama.cpp
    "This model's maximum context length is 32768 tokens. However, you requested 40000 tokens",  # OpenAI/vLLM
    "Error code: 400 - {'error': {'type': 'exceed_context_size_error'}}",
])
def test_context_refusal_is_raised_after_one_request(message):
    async def run():
        models = Models([ContextRefused(message), reply("never used"), reply("never used")])
        with pytest.raises(ContextRefused):
            await execute(client=Client(models), model="m", prompt="hi", image_paths=[], stream_tokens=True,
                          request_extras=lambda tools: {"cache_prompt": True})
        # Before: stream+cache fields, stream without them, then a non-streamed request: three refusals.
        assert len(models.requests) == 1
    asyncio.run(run())


def test_other_400s_still_fall_back_without_cache_fields_and_streaming():
    class Refused(Exception):
        status_code = 400

    async def run():
        models = Models([Refused("unknown field cache_prompt"), Refused("stream not supported"), reply("plain")])
        answer, _, _ = await execute(client=Client(models), model="m", prompt="hi", image_paths=[],
                                     stream_tokens=True, request_extras=lambda tools: {"cache_prompt": True})
        assert answer == "plain" and len(models.requests) == 3
        assert "extra_body" not in models.requests[1] and "stream" not in models.requests[2]
    asyncio.run(run())


def test_is_context_refusal_reads_the_error_body():
    error = ContextRefused("Error code: 400")
    error.body = {"error": {"message": "prompt is too long: 9000 tokens > 8192"}}
    assert agent.is_context_refusal(error)
    assert not agent.is_context_refusal(ContextRefused("unknown field: id_slot"))
