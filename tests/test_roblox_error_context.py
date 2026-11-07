"""Drive the real desktop/agent path; only external services are fakes."""
from contextlib import asynccontextmanager
from copy import deepcopy
import socket
import sys
import traceback
from types import SimpleNamespace

import httpx
import pytest

from star import desktop_core, doc_grounding, roblox_cloud, roblox_errors
from star.agent import system_prefix
from star.brain_router import ROBLOX_QUALITY_NOTES
from star.desktop_core import Conversations, Settings, run_task


OUTPUT = """Roblox Studio output:
12:34:56.001  ServerScriptService.Main:17: attempt to index nil with 'Name'  -  Server - Main:17
12:34:56.002  Stack Begin  -  Studio
12:34:56.003  Script 'ServerScriptService.Main', Line 17 - function startRound  -  Studio
12:34:56.004  Stack End  -  Studio"""
ANSWER = "Check the instance at the failing line before accessing its Name."


class FakeModel:
    def __init__(self):
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        # execute appends to its message list after the response; keep the sent snapshot.
        self.requests.append(deepcopy(kwargs))
        message = SimpleNamespace(content=ANSWER, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeKnowledge:
    def __init__(self, unavailable=False):
        self.unavailable, self.searches = unavailable, []

    def search(self, query, *, top=4, mode="vector", scope=None):
        self.searches.append(query)
        if self.unavailable:
            raise OSError("Documentation service unavailable")
        return [{"rank": 1, "title": "Instance", "heading": "Instance > WaitForChild",
                 "kind": "api", "url": "https://create.roblox.com/docs/reference/engine/classes/Instance",
                 "source": "creator-docs", "path": "Instance.yaml", "commit": "fixture",
                 "licence": "CC-BY-4.0", "retrieved_at": "2026-10-11T00:00:00Z",
                 "text": "WaitForChild waits for the named child; a timeout can return nil."}]

    def api_lookup(self, symbols):
        return []

    def luau_check(self, code, *, strict=False):
        raise AssertionError("The plain-text fake answer contains no Luau to check")


@pytest.fixture
def offline(monkeypatch):
    """A swallowed external-service exception must not hide an accidental network/keyring call."""
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(" -> ".join(frame.name for frame in traceback.extract_stack(limit=6)[:-1]))
        raise AssertionError("Unexpected external service call")

    async def forbidden_async(*args, **kwargs):
        forbidden(*args, **kwargs)

    # Guard application I/O, not socket.connect: Windows asyncio uses it for
    # its local socketpair. The optional keyring package need not be installed.
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_async)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(
        get_password=forbidden, set_password=forbidden, delete_password=forbidden))
    yield
    assert calls == []


def setup_turn(monkeypatch, tmp_path, knowledge=None):
    model = FakeModel()
    home = tmp_path / "STAR"

    @asynccontextmanager
    async def client(settings, **_):
        yield model

    monkeypatch.setattr(desktop_core, "app_data", lambda: home)
    monkeypatch.setattr(desktop_core, "open_client", client)
    monkeypatch.setattr(doc_grounding, "client_for", lambda settings: knowledge)
    # Agent mode constructs RobloxCloud even without a cloud request. Fake its
    # credential lookup, not the real local-intelligence or chat execution path.
    monkeypatch.setattr(roblox_cloud, "load_key", lambda: (None, ""))
    settings = Settings(model="m", knowledge_endpoint="off", specialists_enabled=False,
                        tool_workshop_enabled=False, graphify_enabled=False,
                        learning_auto_accept=False, learning_digest=False)
    return model, settings, home


def text(message):
    content = message["content"]
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


@pytest.mark.parametrize("mode", ["fast", "auto", "agent"])
@pytest.mark.parametrize("docs", ["off", "ok", "unavailable"])
def test_run_task_attaches_local_explanations_to_final_user_turn(monkeypatch, tmp_path, offline, mode, docs):
    knowledge = None if docs == "off" else FakeKnowledge(unavailable=docs == "unavailable")
    model, settings, _ = setup_turn(monkeypatch, tmp_path, knowledge)
    answer = run_task(settings, OUTPUT, mode=mode)
    assert answer.startswith(ANSWER)
    assert len(model.requests) == 1
    request = model.requests[0]
    messages = request["messages"]
    assert [m["role"] for m in messages].count("system") == 1
    assert messages[0] == {"role": "system", "content": system_prefix(
        tools_attached=bool(request.get("tools")), guidance=ROBLOX_QUALITY_NOTES)}
    assert messages[-1]["role"] == "user"
    final = text(messages[-1])
    assert final.startswith(OUTPUT)
    assert final.count(roblox_errors.REFERENCE_OPEN) == 1
    assert roblox_errors.BLOCK_HEADING in final and "[index-nil]" in final
    assert final.index(OUTPUT) < final.index(roblox_errors.REFERENCE_OPEN)
    assert "Distinguishing check:" in final and "Fix pattern:" in final
    assert roblox_errors.RULES[0].example in final
    assert roblox_errors.REFERENCE_CLOSE in final
    assert all(roblox_errors.BLOCK_HEADING not in text(m) for m in messages[:-1])
    if knowledge is not None:
        assert knowledge.searches
    if docs == "ok":
        assert doc_grounding.REFERENCE_OPEN in final
        assert final.index(doc_grounding.REFERENCE_OPEN) < final.index(roblox_errors.REFERENCE_OPEN)
    else:
        assert doc_grounding.REFERENCE_OPEN not in final


@pytest.mark.parametrize("prompt", [
    "Thanks, that helped.",
    "HTTP 429 means too many requests; explain exponential backoff.",
    "I want a warning about an invalid argument in ordinary prose.",
    "Roblox Studio output:\n12:34:56.001  Round started  -  Server - Main:17",
    "Roblox Studio output:\nError: A new diagnostic with no known explanation",
])
def test_real_turn_does_not_add_unmatched_reference_context(monkeypatch, tmp_path, offline, prompt):
    model, settings, _ = setup_turn(monkeypatch, tmp_path)
    assert run_task(settings, prompt, mode="fast") == ANSWER
    assert len(model.requests) == 1
    messages = model.requests[0]["messages"]
    assert all(roblox_errors.BLOCK_HEADING not in text(m) for m in messages)
    assert all(roblox_errors.REFERENCE_OPEN not in text(m) for m in messages)


def test_explanations_are_not_replayed_or_promoted_to_system_memory(monkeypatch, tmp_path, offline):
    model, settings, home = setup_turn(monkeypatch, tmp_path)
    chats = Conversations(home / "conversations.sqlite3")
    try:
        chat_id = chats.new_chat(settings.project)
        chats.add(settings.project, "user", OUTPUT, chat_id=chat_id)
        answer = run_task(settings, OUTPUT, mode="fast", chat_id=chat_id)
        chats.add(settings.project, "assistant", answer, chat_id=chat_id)
        followup = "Thanks, that helped."
        chats.add(settings.project, "user", followup, chat_id=chat_id)
        run_task(settings, followup, mode="fast", chat_id=chat_id)
        assert len(model.requests) == 2
        first, second = (request["messages"] for request in model.requests)
        assert first[0] == second[0]
        assert roblox_errors.REFERENCE_OPEN in text(first[-1])
        assert all(roblox_errors.REFERENCE_OPEN not in text(m) for m in second)
        assert all(roblox_errors.BLOCK_HEADING not in text(m) for m in second)
        assert any(OUTPUT in text(m) for m in second[1:-1]), "Original history is still present"
        stored = chats.raw_history_records(settings.project, chat_id)
        assert stored[0]["body"] == OUTPUT
        assert all(roblox_errors.BLOCK_HEADING not in row["body"] for row in stored)
    finally:
        chats.close()


def test_new_error_gets_its_own_explanation_not_the_previous_one(monkeypatch, tmp_path, offline):
    model, settings, _ = setup_turn(monkeypatch, tmp_path)
    run_task(settings, OUTPUT, mode="fast")
    other = "ServerScriptService.Main:28: attempt to call a nil value"
    run_task(settings, other, mode="fast")
    first, second = (text(request["messages"][-1]) for request in model.requests)
    assert "[index-nil]" in first and "[call-nil]" not in first
    assert "[call-nil]" in second and "[index-nil]" not in second
    assert model.requests[0]["messages"][0] == model.requests[1]["messages"][0]
