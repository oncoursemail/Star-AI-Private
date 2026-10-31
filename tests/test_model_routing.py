"""Model routing on a STAR Server that offers a fleet instead of one model.

Covers: the role table read from /v1/models, a role set by hand always winning,
the fall-back to the single configured model, cloud and on-PC providers left
exactly as they were, one slot per conversation and model, background work sent
without a slot, the tool list of a conversation staying byte-identical from turn
to turn, the warm-up following the last request, the history budget, and the
voice call reading the app's own settings.
"""
import asyncio
import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest

import star.desktop_core as core
import star.providers as providers
from star import server_roles, turn_memory
from star.agent import RULES, FAST_RULES, execute
from star.brain_router import deep_request, select_route
from star.desktop_core import Conversations, Settings, history_char_budget, run_task
from star.model_health import probe_server, server_status
from star.providers import (background_client, llama_request_fields, model_unavailable, remember_server_limits,
                            server_context_tokens, server_slots)
from star.react_shell import sanitize_event
from star.turn_memory import TurnMemory
from star.warmup import prefix_requests

LAN = "http://192.168.1.20:8080/v1"
KEY = "test-server-key-0123456789"

# The `data` array of /v1/models as a llama.cpp router with a fleet reports it.
FLEET = [
    {"id": "star-deep", "aliases": [], "status": {"value": "unloaded"},
     "architecture": {"input_modalities": ["text"]}},
    {"id": "star-embed", "aliases": [], "status": {"value": "loaded"}},
    {"id": "star-fast", "aliases": ["star-code", "star-vision"], "status": {"value": "loaded"},
     "architecture": {"input_modalities": ["text", "image", "video"]}},
    {"id": "star-rerank", "aliases": [], "status": {"value": "loaded"}},
    {"id": "star-voice", "aliases": ["star-quick"], "status": {"value": "loaded"},
     "architecture": {"input_modalities": ["text"]}},
]
ROBLOX_QUESTION = "How do I tween a part with TweenService in Roblox?"


@pytest.fixture(autouse=True)
def clean_process_memory():
    def clear():
        server_roles.forget()
        turn_memory.forget()
        providers._SERVER_LIMITS.clear()
        providers._MODEL_NAMES.clear()
        providers._SLOT_TABLE.clear()
    clear()
    yield
    clear()


def lan_settings(**fields) -> Settings:
    return Settings(**{"provider": "star_server", "server_endpoint": LAN, "model": "star-fast",
                       "knowledge_endpoint": "off", "verify_ladder": "off", **fields})


def fleet_settings(**fields) -> Settings:
    """STAR Server selected and its model list already read."""
    settings = lan_settings(**fields)
    server_roles.remember_models(LAN, FLEET)
    return settings


def routed(settings, prompt, **options):
    return select_route(server_roles.effective(settings), prompt, **options)


# ------------------------------------------------------------------ role table

@pytest.mark.parametrize("listed, expected", [
    (FLEET, {"quick": "star-voice", "code": "star-fast", "vision": "star-vision", "deep": "star-deep"}),
    # One model, no aliases, reads images: it is the code model and the vision model. No quick, no deep.
    ([{"id": "star-fast", "architecture": {"input_modalities": ["text", "image"]}}],
     {"code": "star-fast", "vision": "star-fast"}),
    # The same without image input: no vision role at all.
    ([{"id": "star-fast", "architecture": {"input_modalities": ["text"]}}], {"code": "star-fast"}),
    # Roles reached only through aliases of differently named models.
    ([{"id": "qwen-main", "aliases": ["star-code"]}, {"id": "small", "aliases": ["star-quick"]}],
     {"code": "star-code", "quick": "star-quick"}),
    # `star-vision` offered, but the server says that model cannot read images.
    ([{"id": "star-fast", "aliases": ["star-vision"], "architecture": {"input_modalities": ["text"]}}],
     {"code": "star-fast"}),
    # A model the server failed to load is not offered.
    ([{"id": "star-fast"}, {"id": "star-voice", "status": {"value": "unloaded", "failed": True}}],
     {"code": "star-fast"}),
    # Embedding and rerank models, other names and junk entries map to nothing.
    ([{"id": "star-embed"}, {"id": "star-rerank"}, {"id": "llama-3"}, {"name": "x"}, "text", None, {"id": 7}], {}),
    ([], {}),
    (None, {}),
])
def test_role_table(listed, expected):
    assert server_roles.map_roles(server_roles.parse_models(listed)) == expected


def test_discovered_roles_fill_only_blank_fields_and_are_never_saved(tmp_path):
    settings = fleet_settings()
    before = asdict(settings)
    filled = server_roles.effective(settings)
    assert (filled.fast_model, filled.reasoning_model, filled.roblox_model, filled.vision_model) == (
        "star-voice", "star-fast", "star-fast", "star-vision")
    assert filled.model == "star-fast" and filled is not settings
    assert asdict(settings) == before                      # the owner's settings object is untouched
    file = tmp_path / "settings.json"
    settings.save(file)
    saved = json.loads(file.read_text(encoding="utf-8"))
    assert saved["fast_model"] == saved["reasoning_model"] == saved["vision_model"] == ""


def test_a_role_set_by_hand_is_never_overwritten():
    settings = fleet_settings(fast_model="my-quick", vision_model="my-eyes")
    filled = server_roles.effective(settings)
    assert filled.fast_model == "my-quick" and filled.vision_model == "my-eyes"
    assert filled.reasoning_model == "star-fast"           # the blank ones are still filled
    assert routed(settings, "hello there", mode="fast").model == "my-quick"
    assert routed(settings, "what is in this picture?", mode="fast", image_count=1).model == "my-eyes"
    by_role = {entry["role"]: entry for entry in server_roles.role_report(settings)}
    assert by_role["quick"] == {"role": "quick", "label": "Quick chat", "model": "my-quick", "source": "manual"}
    assert by_role["code"]["source"] == "server" and by_role["vision"]["source"] == "manual"
    # A hand-set code model also wins for Agent mode.
    assert routed(fleet_settings(reasoning_model="my-coder", roblox_model="my-coder"),
                  "refactor the inventory module", mode="agent").model == "my-coder"


@pytest.mark.parametrize("prompt, options, model", [
    ("hello there", {"mode": "fast"}, "star-voice"),                           # quick chat
    ("What is the capital of France?", {"mode": "auto"}, "star-voice"),
    (ROBLOX_QUESTION, {"mode": "fast"}, "star-fast"),                          # Roblox: grounded, main model
    ("why does my luau loop never end?", {"mode": "fast"}, "star-fast"),
    ("write a python function that reverses a list", {"mode": "fast"}, "star-fast"),   # coding
    ("```\nprint(1)\n```\nwhat does this print?", {"mode": "fast"}, "star-fast"),
    ("plan the architecture of my inventory system", {"mode": "auto"}, "star-fast"),
    ("tidy the files in my project", {"mode": "auto", "project_tools": True}, "star-fast"),   # tool use
    ("hello there", {"mode": "agent"}, "star-fast"),                           # Agent mode
    (ROBLOX_QUESTION, {"mode": "agent"}, "star-fast"),
    ("what is in this picture?", {"mode": "fast", "image_count": 1}, "star-vision"),   # images
    ("what is in this picture?", {"mode": "agent", "image_count": 2}, "star-vision"),
])
def test_fleet_routes(prompt, options, model):
    assert routed(fleet_settings(), prompt, **options).model == model


def test_a_fast_mode_roblox_question_is_still_grounded_and_sub_agents_use_the_quick_model():
    route = routed(fleet_settings(), ROBLOX_QUESTION, mode="fast")
    assert route.model == "star-fast" and route.grounding.retrieve != "none" and route.grounding.check_luau
    agent = routed(fleet_settings(), "compare two designs", mode="agent")
    assert (agent.model, agent.subagent_model) == ("star-fast", "star-voice")


def test_the_deep_model_only_answers_when_the_owner_asks_for_it():
    settings = fleet_settings()
    prompts = ["hello", ROBLOX_QUESTION, "research and compare the architecture in depth, think hard",
               "deep dive into this complex design", "write code"]
    for mode in ("fast", "auto", "agent"):
        for prompt in prompts:
            for flags in ({}, {"research": True}, {"project_tools": True}, {"image_count": 1}):
                assert routed(settings, prompt, mode=mode, **flags).model != "star-deep"
    assert deep_request("/deep explain the trade-offs") == (True, "explain the trade-offs")
    assert deep_request("Please use the deep model for this one")[0] is True
    assert deep_request("use star-deep: why is the sky blue?")[0] is True
    assert deep_request("a deep dive into /deep folders") == (False, "a deep dive into /deep folders")
    assert deep_request("/deep") == (True, "/deep")        # nothing to ask: the text stays as typed
    asked = select_route(server_roles.effective(settings), "explain the trade-offs", mode="fast",
                         deep_model=server_roles.deep_model(settings))
    assert asked.model == "star-deep" and asked.task_timeout > routed(settings, "hello", mode="fast").task_timeout
    # An image never goes to the text-only deep model.
    assert select_route(server_roles.effective(settings), "what is this?", mode="fast", image_count=1,
                        deep_model="star-deep").model == "star-vision"
    # A server without one: asking changes nothing.
    server_roles.remember_models(LAN, [FLEET[2], FLEET[4]])
    assert server_roles.deep_model(settings) == ""


# ------------------------------------------------------------------ fall-back

def test_a_missing_role_falls_back_to_the_single_configured_model():
    settings = lan_settings(model="my-main")
    assert server_roles.effective(settings) is settings             # the server was never asked
    assert routed(settings, "hello", mode="fast").model == "my-main"
    server_roles.remember_models(LAN, [{"id": "my-main"}, {"id": "star-embed"}])
    for prompt, options in (("hello", {"mode": "fast"}), (ROBLOX_QUESTION, {"mode": "fast"}),
                            ("hello", {"mode": "agent"}), ("look", {"mode": "fast", "image_count": 1})):
        assert routed(settings, prompt, **options).model == "my-main"


def test_a_model_that_failed_is_not_routed_to_again_until_the_server_is_asked_again():
    settings = fleet_settings()
    assert routed(settings, "hello", mode="fast").model == "star-voice"
    server_roles.mark_failed(settings, "star-quick")                 # by alias: the same model
    assert routed(settings, "hello", mode="fast").model == "star-fast"
    assert routed(settings, ROBLOX_QUESTION, mode="fast").model == "star-fast"
    server_roles.remember_models(LAN, FLEET)                          # the next check brings it back
    assert routed(settings, "hello", mode="fast").model == "star-voice"


def test_model_unavailable_recognises_what_a_router_answers():
    def error(status, message=""):
        failure = RuntimeError(message)
        failure.status_code, failure.message = status, message
        return failure
    assert model_unavailable(error(400, "model 'star-voice' not found"))
    assert model_unavailable(error(404)) and model_unavailable(error(503)) and model_unavailable(error(500))
    assert not model_unavailable(error(400, "the request exceeds the available context size"))
    assert not model_unavailable(error(401)) and not model_unavailable(error(429))
    assert not model_unavailable(TimeoutError()) and not model_unavailable(RuntimeError("cancelled"))


def reply(content=None, calls=None, model=None):
    return SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(content=content,
                                                                                         tool_calls=calls))])


class Models:
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


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A private app-data folder, a STAR Server with a fleet, and a fake model client behind run_task."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    models = Models()
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    chats = Conversations(home / "conversations.sqlite3")
    chat = chats.new_chat("STAR")
    settings = fleet_settings()
    for name in ("star-fast", "star-voice"):
        remember_server_limits(LAN, name, 32768, 2)
    events = []

    def turn(text, answer, **options):
        chats.add("STAR", "user", text, chat_id=chat)
        models.responses.extend(answer if isinstance(answer, list) else [reply(answer)])
        result = run_task(options.pop("settings", settings), text, chat_id=chat, on_event=events.append,
                          **{"mode": "fast", **options})
        chats.add("STAR", "assistant", result, chat_id=chat)
        return models.requests[-1]

    yield SimpleNamespace(models=models, home=home, chats=chats, chat=chat, settings=settings, turn=turn,
                          events=events)
    chats.close()


def not_found(model):
    failure = RuntimeError(f"model '{model}' not found")
    failure.status_code, failure.message = 400, f"model '{model}' not found"
    return failure


def test_run_task_sends_each_message_to_its_role_and_records_who_answered(desk):
    quick = desk.turn("hello there", [reply("Hi!", model="star-voice")])
    assert quick["model"] == "star-voice"
    roblox = desk.turn(ROBLOX_QUESTION, [reply("Use TweenService:Create.", model="star-fast")])
    assert roblox["model"] == "star-fast"
    chosen = [event for event in desk.events if event.get("event") == "route_selected"]
    assert [event["model"] for event in chosen] == ["star-voice", "star-fast"]
    answered = [event["model"] for event in desk.events if event.get("event") == "model_answered"]
    assert answered == ["star-voice", "star-fast"]
    records = sorted((desk.home / "runs").glob("*/transcript.json"))
    assert [json.loads(record.read_text(encoding="utf-8"))["route"] for record in records] == [
        {"profile": "fast", "requested_model": "star-voice", "answered_model": "star-voice"},
        {"profile": "fast", "requested_model": "star-fast", "answered_model": "star-fast"}]


def test_run_task_falls_back_to_the_configured_model_when_the_role_model_is_gone(desk):
    # Both attempts on star-voice fail (the second is the retry without the llama.cpp fields).
    request = desk.turn("hello there", [not_found("star-voice"), not_found("star-voice"),
                                        reply("Hi from the main model.", model="star-fast")])
    assert [sent["model"] for sent in desk.models.requests] == ["star-voice", "star-voice", "star-fast"]
    assert request["model"] == "star-fast"
    kinds = [event.get("event") for event in desk.events]
    assert "route_fallback" in kinds and kinds.index("route_fallback") < kinds.index("model_answered")
    # The broken role is skipped from now on: no second failure for the next message.
    again = desk.turn("and how are you?", [reply("Fine.", model="star-fast")])
    assert again["model"] == "star-fast" and len(desk.models.requests) == 4


def test_run_task_does_not_retry_other_failures_or_the_configured_model_itself(desk):
    busy = RuntimeError("rate limited")
    busy.status_code = 429
    desk.chats.add("STAR", "user", "hello there", chat_id=desk.chat)
    desk.models.responses.append(busy)
    with pytest.raises(RuntimeError, match="rate limited"):
        run_task(desk.settings, "hello there", chat_id=desk.chat, mode="fast")
    assert len(desk.models.requests) == 1
    desk.models.responses.extend([not_found("star-fast"), not_found("star-fast")])
    with pytest.raises(RuntimeError, match="not found"):
        run_task(desk.settings, ROBLOX_QUESTION, chat_id=desk.chat, mode="fast")   # routed to the primary already
    assert [sent["model"] for sent in desk.models.requests[1:]] == ["star-fast", "star-fast"]


def test_slash_deep_reaches_the_deep_model_without_the_command_text(desk):
    request = desk.turn("/deep explain why the sky is blue", [reply("Rayleigh scattering.", model="star-deep")])
    assert request["model"] == "star-deep"
    final = request["messages"][-1]["content"]
    text = final if isinstance(final, str) else final[0]["text"]
    assert text.startswith("explain why the sky is blue") and "/deep" not in text


# ------------------------------------------------------------------ cloud and on-PC untouched

@pytest.mark.parametrize("provider", ["local", "groq", "openrouter", "gemini", "cerebras"])
def test_other_providers_are_exactly_as_before(provider):
    settings = Settings(provider=provider, model="main", fast_model="small", reasoning_model="big",
                        server_endpoint=LAN)
    plain = Settings(provider=provider, model="main", server_endpoint=LAN)
    cases = [("hello", {"mode": "fast"}), (ROBLOX_QUESTION, {"mode": "fast"}),
             ("write a python function", {"mode": "fast"}), ("plan the design", {"mode": "auto"}),
             ("hello", {"mode": "agent"}), ("look", {"mode": "fast", "image_count": 1})]
    before = [(select_route(settings, prompt, **options), select_route(plain, prompt, **options))
              for prompt, options in cases]
    server_roles.remember_models(LAN, FLEET)                 # a fleet at the saved server address
    remember_server_limits(LAN, "main", 32768, 2)
    assert server_roles.effective(settings) is settings and server_roles.effective(plain) is plain
    assert server_roles.discovered_roles(settings) == {} and server_roles.role_report(plain)[0]["source"] == "default"
    after = [(select_route(server_roles.effective(settings), prompt, **options),
              select_route(server_roles.effective(plain), prompt, **options)) for prompt, options in cases]
    assert after == before
    # The old table: Fast mode always uses the small model, also for Roblox and code.
    assert [route.model for route, _ in after[:3]] == ["small", "small", "small"]
    assert {route.model for _, route in after} == {"main"}
    fields = llama_request_fields(settings, conversation="c", model="main", background=True)
    assert "id_slot" not in fields and (fields == {} if provider != "local" else fields["cache_prompt"] is True)
    client = object()
    assert background_client(client, settings, conversation="c") is client
    assert history_char_budget(settings) == (6000 if provider == "local" else 12000)
    assert server_status(settings)["roles"] == []


def test_sticky_tools_are_off_for_other_providers(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    seen = {}

    async def fake_execute(**kwargs):
        seen[kwargs["model"]] = kwargs["tool_memory"]
        return "ok", [], []
    monkeypatch.setattr(core, "execute", fake_execute)
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(Models()))
    run_task(Settings(provider="groq", model="cloud-model"), "hello", mode="fast")
    run_task(Settings(model="pc-model"), "hello", mode="fast")
    assert seen["cloud-model"] is None                        # a hosted provider: nothing remembered
    assert seen["pc-model"].sticky is False                   # on this PC: the tool list follows the prompt


# ------------------------------------------------------------------ the server check

def fleet_server(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": FLEET})
        if request.url.path == "/props":
            slots = {"star-fast": (32768, 2), "star-voice": (16384, 2)}[request.url.params["model"]]
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": slots[0]},
                                             "total_slots": slots[1]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_the_server_check_reads_the_roles_once_and_never_asks_about_an_unloaded_model(monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    settings = lan_settings()
    seen = []
    report = probe_server(settings, transport=fleet_server(seen), chat=False)
    assert report["ok"] is True
    assert [path for path, _ in seen].count("/v1/models") == 1
    asked = [params["model"] for path, params in seen if path == "/props"]
    assert sorted(asked) == ["star-fast", "star-voice"]        # loaded role models, each once
    assert "star-deep" not in asked                            # asking would load 23 GB
    assert {entry["role"]: entry["model"] for entry in report["roles"]} == {
        "quick": "star-voice", "code": "star-fast", "vision": "star-vision", "deep": "star-deep"}
    assert server_status(settings)["roles"] == report["roles"]
    assert KEY not in json.dumps(report)
    # Limits are per model, and an alias shares its model's entry.
    assert (server_slots(settings, "star-voice"), server_context_tokens(settings, "star-voice")) == (2, 16384)
    assert (server_slots(settings, "star-vision"), server_context_tokens(settings, "star-code")) == (2, 32768)
    assert server_slots(settings, "star-deep") == 0
    assert routed(settings, "hello", mode="fast").model == "star-voice"


# ------------------------------------------------------------------ slot affinity

def slot(settings, conversation, **options):
    return llama_request_fields(settings, conversation=conversation, **options).get("id_slot")


def test_one_conversation_keeps_one_slot_on_each_model():
    settings = fleet_settings()
    assert slot(settings, "chat-a", model="star-fast") is None            # slot count not known yet
    remember_server_limits(LAN, "star-fast", 32768, 2)
    first = slot(settings, "chat-a", model="star-fast")
    assert first in (0, 1)
    for options in ({}, {"tools": True}, {"prime": True}, {"tools": True, "prime": True}):
        assert slot(settings, "chat-a", model="star-fast", **options) == first
    assert slot(settings, "chat-a", model="star-vision") == first         # an alias is the same model
    assert slot(settings, "chat-a", model="star-voice") is None           # another model: its slots are unknown
    remember_server_limits(LAN, "star-voice", 16384, 2)
    assert slot(settings, "chat-a", model="star-voice") in (0, 1)
    remember_server_limits(LAN, "star-fast", 32768, 1)                    # a one-slot server is never pinned
    assert slot(settings, "chat-a", model="star-fast") is None


def test_background_work_is_never_pinned_and_changes_no_chats_slot():
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)
    for number in range(12):
        chat = f"STAR::chat::{number}"
        own = slot(settings, chat, model="star-fast")                     # a real turn: this chat is open
        before = copy.deepcopy(providers._SLOT_TABLE)
        for other in (chat, "lesson-summary", "another-chat", ""):
            for options in ({}, {"tools": True}, {"prime": True}):
                fields = llama_request_fields(settings, conversation=other, model="star-fast", background=True,
                                              **options)
                assert fields == {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}}
        # Background work is not a chat: it takes no slot of its own and does not become the open chat.
        assert providers._SLOT_TABLE == before
        assert slot(settings, chat, model="star-fast") == own             # and the chat is still where it was


def test_a_request_without_a_conversation_is_not_pinned():
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)
    for options in ({}, {"prime": True}, {"tools": True}):
        assert slot(settings, "", model="star-fast", **options) is None
    assert providers._SLOT_TABLE == {}


def test_a_chat_finds_its_slot_again_after_a_restart():
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)
    chats = [f"STAR::chat::{number}" for number in range(16)]
    first = {}
    for chat in chats:
        providers._SLOT_TABLE.clear()                                     # a new process: nothing remembered
        first[chat] = slot(settings, chat, model="star-fast")
    assert set(first.values()) == {0, 1}                                  # not every chat on one slot
    for chat in reversed(chats):                                          # another process, another order
        providers._SLOT_TABLE.clear()
        assert slot(settings, chat, model="star-fast", prime=True) == first[chat]


def test_a_chat_opened_next_to_the_active_one_takes_the_other_slot():
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)
    active = slot(settings, "chat-a", model="star-fast")
    # Warm-ups of other chats (the owner clicks through the sidebar) never land on chat-a's slot.
    for number in range(8):
        assert slot(settings, f"other-{number}", model="star-fast", prime=True) == 1 - active
    assert slot(settings, "chat-a", model="star-fast") == active
    # The owner writes in one of them: it keeps the slot it was primed on and is now the open chat.
    assert slot(settings, "other-3", model="star-fast") == 1 - active
    assert slot(settings, "x", model="star-fast", background=True) is None
    # A chat opened now is kept off other-3's slot, which shows other-3 is the open chat.
    assert slot(settings, "other-9", model="star-fast", prime=True) == active
    # Back to chat-a: still its old slot, where the server still holds its prompt.
    assert slot(settings, "chat-a", model="star-fast") == active


def test_helper_calls_carry_the_cache_fields_and_no_slot(desk):
    own = slot(desk.settings, "STAR::chat::" + desk.chat, model="star-fast")
    models = Models([reply("summary"), not_found("x"), reply("after the refusal")])
    helper = background_client(Client(models), desk.settings, conversation="STAR::chat::" + desk.chat)

    async def run():
        first = await helper.chat.completions.create(model="star-fast", messages=[], max_tokens=5)
        second = await helper.chat.completions.create(model="star-fast", messages=[])
        return first, second
    first, second = asyncio.run(run())
    assert first.choices[0].message.content == "summary"
    assert models.requests[0]["extra_body"] == {"cache_prompt": True,
                                                "chat_template_kwargs": {"preserve_thinking": True}}
    assert models.requests[0]["max_tokens"] == 5
    # A server that refuses the fields is asked again without them, once.
    assert "extra_body" not in models.requests[2] and second.choices[0].message.content == "after the refusal"
    assert slot(desk.settings, "STAR::chat::" + desk.chat, model="star-fast") == own


def test_a_chat_turn_is_pinned_and_its_sub_agents_are_not_through_run_task(desk):
    request = desk.turn(ROBLOX_QUESTION, [reply("Use TweenService:Create.", model="star-fast")])
    own = request["extra_body"]["id_slot"]
    assert own == slot(desk.settings, "STAR::chat::" + desk.chat, model="star-fast")
    quick = desk.turn("thanks!", [reply("You're welcome.", model="star-voice")])
    assert quick["model"] == "star-voice" and quick["extra_body"]["id_slot"] in (0, 1)
    # An Agent turn that delegates: the model's own two requests go to the chat's slot, the two
    # sub-agent requests between them (the real star_delegate path) carry no slot.
    tasks = json.dumps({"tasks": ["Compare two ways to store the inventory.", "List the risks of each way."]})
    sent = len(desk.models.requests)
    desk.turn("Use a skill and delegate research to a team of agents",
              [reply(calls=[tool_call("star_delegate", tasks)], model="star-fast"), reply("draft one"),
               reply("draft two"), reply("Both drafts are in.", model="star-fast")], mode="agent")
    asked, first_draft, second_draft, final = desk.models.requests[sent:]
    assert asked["model"] == final["model"] == "star-fast"
    assert asked["extra_body"]["id_slot"] == final["extra_body"]["id_slot"] == own
    assert "draft one" in json.dumps(final["messages"]) and "draft two" in json.dumps(final["messages"])
    for draft in (first_draft, second_draft):
        assert "subagent" in draft["messages"][0]["content"] and "tools" not in draft
        assert draft["extra_body"] == {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}}


class SlotServer:
    """A model with numbered slots, as llama.cpp serves it: a request that names a slot waits
    for that slot, a request that names none takes any free one. Records what each request
    named and who had to wait. A slot stays taken until `together` requests have arrived, so
    requests sent at the same moment really meet."""

    def __init__(self, slots=2, together=2):
        self.count = slots
        self.free = set(range(slots))
        self.together = together
        self.changed = None
        self.named, self.waited = [], []
        self.arrived = self.running = self.peak = 0

    async def create(self, **kwargs):
        self.changed = self.changed or asyncio.Condition()
        wanted = (kwargs.get("extra_body") or {}).get("id_slot")
        self.named.append(wanted)

        def usable():
            return self.free if wanted is None else self.free & {wanted}
        async with self.changed:
            self.arrived += 1
            self.changed.notify_all()
            if not usable():
                self.waited.append(wanted)
                await self.changed.wait_for(usable)
            taken = min(usable())
            self.free.discard(taken)
            self.running += 1
            self.peak = max(self.peak, self.running)
            # Still generating while the other request arrives. The time limit only keeps a
            # broken test from hanging: the assertions on `peak` and `waited` then fail.
            try:
                await asyncio.wait_for(self.changed.wait_for(lambda: self.arrived >= self.together), 10)
            except TimeoutError:
                pass
        async with self.changed:
            self.running -= 1
            self.free.add(taken)
            self.changed.notify_all()
        return reply(f"slot {taken}")

    def slots_page(self, seen=None):
        """`GET /slots?model=X` of this server, as an httpx mock transport (llama.cpp's fields)."""
        def answer(request):
            if seen is not None:
                seen.append(request)
            return httpx.Response(200, json=[{"id": number, "id_task": -1, "is_processing": number not in self.free}
                                             for number in range(self.count)])
        return httpx.MockTransport(answer)


def test_two_helpers_at_once_do_not_wait_for_the_same_slot(desk):
    """Issue 118: helpers pinned to one slot queued behind each other while the other slot was free."""
    from star.subagents import delegate
    scope = "STAR::chat::" + desk.chat
    slot(desk.settings, scope, model="star-voice")                       # the chat is open
    server = SlotServer(2)
    helper = background_client(Client(server), desk.settings, conversation=scope)
    drafts = asyncio.run(delegate(helper, "star-voice", ["Compare two ways to store the inventory.",
                                                         "List the risks of each way."]))
    assert sorted(piece["draft"] for piece in drafts) == ["slot 0", "slot 1"]
    assert server.peak == 2 and server.waited == [] and server.named == [None, None]

    # Two STAR windows with a chat of the same name, each sending one helper request.
    server = SlotServer(2)

    async def both():
        calls = []
        for _ in range(2):
            providers._SLOT_TABLE.clear()                                  # the other window knows nothing of this one
            slot(desk.settings, scope, model="star-voice")
            window = background_client(Client(server), desk.settings, conversation=scope)
            calls.append(window.chat.completions.create(model="star-voice", messages=[]))
        return await asyncio.gather(*calls)
    answers = asyncio.run(both())
    assert sorted(answer.choices[0].message.content for answer in answers) == ["slot 0", "slot 1"]
    assert server.peak == 2 and server.waited == []


def two_clients_send_a_turn_at_once(settings, server, chats, model="star-fast"):
    """Two STAR clients, each sending one turn of its own chat through the real request code
    (agent.execute, with the fields the app attaches) to the same server at the same moment.
    They are two processes: when a client picks its slot it knows nothing of the other one."""
    async def turn(scope):
        def fields(tools):
            providers._SLOT_TABLE.clear()
            return llama_request_fields(settings, conversation=scope, tools=tools, model=model)
        answer, _, _ = await execute(client=Client(server), model=model, prompt="hello there", image_paths=[],
                                     mode="fast", today="2026-10-10", request_extras=fields)
        return answer

    async def both():
        return await asyncio.gather(*(turn(scope) for scope in chats))
    return asyncio.run(both())


def test_two_clients_sending_a_chat_turn_at_once(monkeypatch):
    """Issue 118, the chat's own turn. Chats of two clients on different slots run side by side.
    Two chats with the same slot number are the known limit of pinning by a hash: the second
    turn waits. With STAR_SERVER_SLOT_PINNING=off no slot is named and nobody waits."""
    monkeypatch.delenv("STAR_SERVER_SLOT_PINNING", raising=False)
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)

    def home(chat):                                                       # the slot a new process gives this chat
        providers._SLOT_TABLE.clear()
        return slot(settings, chat, model="star-fast")
    first, *others = [f"STAR::chat::{number}" for number in range(16)]
    apart = next(chat for chat in others if home(chat) != home(first))
    same = next(chat for chat in others if home(chat) == home(first))

    server = SlotServer(2)
    assert sorted(two_clients_send_a_turn_at_once(settings, server, [first, apart])) == ["slot 0", "slot 1"]
    assert sorted(server.named) == [0, 1] and server.peak == 2 and server.waited == []

    # Sent at the very same moment, without the look at the server's slots the app takes first
    # (see the busy-slot tests below): both clients name one slot and the second waits for it
    # although the other slot is free. Both turns are still answered.
    server = SlotServer(2)
    answers = two_clients_send_a_turn_at_once(settings, server, [first, same])
    assert answers == [f"slot {home(first)}"] * 2
    assert server.named == [home(first)] * 2 and server.waited == [home(first)] and server.peak == 1

    # Opt-in: the server places every request. The same two chats no longer meet in one slot.
    monkeypatch.setenv("STAR_SERVER_SLOT_PINNING", "off")
    server = SlotServer(2)
    assert sorted(two_clients_send_a_turn_at_once(settings, server, [first, same])) == ["slot 0", "slot 1"]
    assert server.named == [None, None] and server.peak == 2 and server.waited == []


def chats_on_one_slot(settings, model="star-fast"):
    """Two chat names that a fresh process puts on the same slot, and that slot."""
    def home(chat):
        providers._SLOT_TABLE.clear()
        return slot(settings, chat, model=model)
    first, *others = [f"STAR::chat::{number}" for number in range(16)]
    same = next(chat for chat in others if home(chat) == home(first))
    shared = home(first)
    providers._SLOT_TABLE.clear()
    return first, same, shared


def test_a_turn_moves_off_a_slot_another_client_is_generating_in(monkeypatch):
    """Issue 118: client B's chat hashes to the slot client A is generating in. B looks at the
    server's slots first, sees that slot busy and sends its turn to the idle one: both run side by
    side, nobody waits, and B's chat stays on its new slot for the next turn."""
    settings = fleet_settings()
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    remember_server_limits(LAN, "star-fast", 32768, 2)
    first, same, shared = chats_on_one_slot(settings)
    server = SlotServer(2)
    seen = []
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", server.slots_page(seen))

    async def client_a():
        def fields(tools):
            providers._SLOT_TABLE.clear()                                # its own process
            return llama_request_fields(settings, conversation=first, tools=tools, model="star-fast")
        return (await execute(client=Client(server), model="star-fast", prompt="hello there", image_paths=[],
                              mode="fast", today="2026-10-10", request_extras=fields))[0]

    async def client_b():
        while server.running == 0:                                       # a moment after A's turn started
            await asyncio.sleep(0)
        providers._SLOT_TABLE.clear()                                    # another process
        busy = await providers.look_for_busy_slots(settings, "star-fast", conversation=same)
        assert busy == {shared}
        moved = llama_request_fields(settings, conversation=same, model="star-fast")
        return (await execute(client=Client(server), model="star-fast", prompt="hello there", image_paths=[],
                              mode="fast", today="2026-10-10", request_extras=moved))[0], moved

    async def both():
        return await asyncio.gather(client_a(), client_b())
    answer_a, (answer_b, moved) = asyncio.run(both())
    assert answer_a == f"slot {shared}" and answer_b == f"slot {1 - shared}"
    assert moved["id_slot"] == 1 - shared
    assert server.named == [shared, 1 - shared] and server.peak == 2 and server.waited == []
    # The look went to the validated server's own /slots page for that model, with the key.
    assert len(seen) == 1
    asked = seen[0]
    assert (asked.method, asked.url.host, asked.url.path) == ("GET", httpx.URL(LAN).host, "/slots")
    assert asked.url.params["model"] == "star-fast"
    assert asked.headers["authorization"] == f"Bearer {KEY}"
    # B's chat keeps the slot it moved to (its prompt is cached there), with no further look.
    assert slot(settings, same, model="star-fast") == 1 - shared
    assert slot(settings, same, model="star-fast", tools=True) == 1 - shared


def test_a_busy_slot_seen_once_moves_one_turn_choice_only(monkeypatch):
    settings = fleet_settings()
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    remember_server_limits(LAN, "star-fast", 32768, 3)
    chat = "STAR::chat::a"
    home = slot(settings, chat, model="star-fast")

    def busy_page(busy):
        return httpx.MockTransport(lambda request: httpx.Response(
            200, json=[{"id": number, "is_processing": number in busy} for number in range(3)]))

    def look(busy):
        monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", busy_page(busy))
        return asyncio.run(providers.look_for_busy_slots(settings, "star-fast", conversation=chat))

    # Other slots busy: nothing moves, and the answer is used up by that turn.
    assert look({(home + 1) % 3}) == {(home + 1) % 3}
    assert slot(settings, chat, model="star-fast") == home
    assert providers._BUSY_SLOTS == {}
    # A warm-up never moves the chat (it prepares the slot the chat is in) and leaves the answer for the turn.
    look({home})
    assert slot(settings, chat, model="star-fast", prime=True) == home
    assert slot(settings, chat, model="star-fast") == (home + 1) % 3       # the turn moves to the next idle one
    assert slot(settings, chat, model="star-fast") == (home + 1) % 3       # and stays
    home = (home + 1) % 3
    # Every slot busy: no idle slot to go to, so the chat keeps its own.
    look({0, 1, 2})
    assert slot(settings, chat, model="star-fast") == home
    # Its slot and the next one busy: the one after.
    look({home, (home + 1) % 3})
    assert slot(settings, chat, model="star-fast") == (home + 2) % 3
    home = (home + 2) % 3
    # An answer older than a few seconds says nothing about now.
    look({home})
    stamp, busy = providers._BUSY_SLOTS[providers._instance(settings, "star-fast")]
    providers._BUSY_SLOTS[providers._instance(settings, "star-fast")] = (stamp - 60, busy)
    assert slot(settings, chat, model="star-fast") == home
    # Older llama.cpp builds report `state` (0 idle) instead of `is_processing`.
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(
        200, json=[{"id": 0, "state": 1}, {"id": 1, "state": 0}, {"id": 2, "state": 1}, "junk", {"id": "3"}])))
    assert asyncio.run(providers.look_for_busy_slots(settings, "star-fast", conversation=chat)) == {0, 2}


@pytest.mark.parametrize("failure", ["refused", "timeout", "server error", "not json", "not a list", "unauthorized"])
def test_a_failed_look_at_the_slots_changes_nothing(monkeypatch, failure):
    settings = fleet_settings()
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    remember_server_limits(LAN, "star-fast", 32768, 2)
    chat = "STAR::chat::a"
    home = slot(settings, chat, model="star-fast")

    def answer(request):
        if failure == "refused":
            raise httpx.ConnectError("refused", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return {"server error": httpx.Response(500, text="boom"), "not json": httpx.Response(200, text="<html>"),
                "not a list": httpx.Response(200, json={"error": "x"}),
                "unauthorized": httpx.Response(401, json={"error": "bad key"})}[failure]
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", httpx.MockTransport(answer))
    assert asyncio.run(providers.look_for_busy_slots(settings, "star-fast", conversation=chat)) == frozenset()
    assert providers._BUSY_SLOTS == {} and providers._NO_SLOTS_PAGE == set()
    assert slot(settings, chat, model="star-fast") == home


def test_the_slots_page_is_only_asked_when_the_turn_would_be_pinned(monkeypatch):
    settings = fleet_settings()
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    asked = []
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", httpx.MockTransport(
        lambda request: asked.append(request) or httpx.Response(404)))

    def look(settings, model="star-fast", conversation="STAR::chat::a"):
        return asyncio.run(providers.look_for_busy_slots(settings, model, conversation=conversation))
    assert look(settings) == frozenset() and asked == []                  # slot count not known yet
    remember_server_limits(LAN, "star-fast", 32768, 1)
    assert look(settings) == frozenset() and asked == []                  # one slot: never pinned
    remember_server_limits(LAN, "star-fast", 32768, 2)
    assert look(settings, conversation="") == frozenset() and asked == []  # no conversation: not pinned
    assert look(Settings(provider="groq", model="x")) == frozenset() and asked == []
    for name in ("STAR_SERVER_SLOT_PINNING", "STAR_SERVER_SLOT_PROBE"):
        monkeypatch.setenv(name, "off")
        assert look(settings) == frozenset() and asked == []
        monkeypatch.delenv(name)
    # A server without the page (llama.cpp --no-slots answers 501, others 404) is asked once per process.
    assert look(settings) == frozenset() and len(asked) == 1
    assert look(settings) == frozenset() and len(asked) == 1
    assert providers._NO_SLOTS_PAGE == {LAN}


def test_a_chat_turn_through_run_task_avoids_a_busy_slot(desk, monkeypatch):
    """The app path: run_task looks at the server's slots before the turn and pins the idle one."""
    scope = "STAR::chat::" + desk.chat
    home = slot(desk.settings, scope, model="star-fast")
    asked = []

    def page(request):
        asked.append(request.url.params.get("model"))
        return httpx.Response(200, json=[{"id": 0, "is_processing": home == 0},
                                         {"id": 1, "is_processing": home == 1}])
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", httpx.MockTransport(page))
    request = desk.turn(ROBLOX_QUESTION, [reply("Use TweenService:Create.", model="star-fast")])
    assert asked == ["star-fast"]
    assert request["extra_body"]["id_slot"] == 1 - home
    assert slot(desk.settings, scope, model="star-fast") == 1 - home


@pytest.mark.parametrize("value, pinned", [("", True), ("on", True), ("1", True), ("anything", True),
                                           ("off", False), (" OFF ", False), ("0", False), ("false", False),
                                           ("no", False)])
def test_slot_pinning_is_on_unless_the_owner_switches_it_off(monkeypatch, value, pinned):
    monkeypatch.setenv("STAR_SERVER_SLOT_PINNING", value)
    settings = fleet_settings()
    remember_server_limits(LAN, "star-fast", 32768, 2)
    cache_only = {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}}
    for options in ({}, {"prime": True}, {"tools": True}):
        fields = llama_request_fields(settings, conversation="STAR::chat::a", model="star-fast", **options)
        assert ("id_slot" in fields) is pinned
        assert {name: value for name, value in fields.items() if name != "id_slot"} == cache_only
    assert llama_request_fields(settings, conversation="STAR::chat::a", model="star-fast",
                                background=True) == cache_only
    assert (providers._SLOT_TABLE != {}) is pinned                        # switched off: no chat is given a slot
    # Not for a cloud provider, whatever the variable says.
    assert llama_request_fields(Settings(provider="groq", model="x"), conversation="a") == {}


# ------------------------------------------------------------------ sticky tools

def tool(name):
    return {"name": name, "description": "does " + name, "inputSchema": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": []}}


class Source:
    """A prompt-gated tool source like star.intelligence: a word in the prompt attaches a tool group."""
    def __init__(self, groups):
        self.groups, self.calls, self.enabled = groups, [], True

    def definitions(self, prompt):
        if not self.enabled:
            return []
        return [tool(name) for word, names in self.groups.items() if word in prompt.lower() for name in names]

    def owns(self, name):
        return any(name in names for names in self.groups.values())

    def call(self, name, args, *, enabled):
        if name not in enabled:
            raise PermissionError(name)
        self.calls.append(name)
        return {"ok": True}


def tool_call(name, arguments="{}"):
    return SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=arguments))


def agent_turn(models, prompt, memory, source, **options):
    asyncio.run(execute(client=Client(models), model="star-fast", prompt=prompt, image_paths=[],
                        intelligence=source, subagents_enabled=True, tool_memory=memory, mode="agent",
                        today="2026-10-10", **options))
    return models.requests[-1]


def test_the_tool_list_of_a_conversation_is_grow_only_ordered_and_byte_identical():
    source = Source({"skill": ["star_skill_catalog", "star_skill_load"], "notes": ["star_obsidian_search"],
                     "graph": ["star_graphify_query"]})
    memory = TurnMemory(sticky=True)
    models = Models([reply("a"), reply("b"), reply("c"), reply("d"), reply("e")])
    first = agent_turn(models, "use a skill for this", memory, source)
    names = [item["function"]["name"] for item in first["tools"]]
    assert names == ["star_delegate", "star_skill_catalog", "star_skill_load"]
    # A message that would select nothing by itself: the same list, byte for byte.
    second = agent_turn(models, "thanks, now summarise it", memory, source)
    assert json.dumps(second["tools"]) == json.dumps(first["tools"])
    assert second["messages"][0] == first["messages"][0]                 # and the same system message
    # A new tool joins at the end; everything before it keeps its bytes.
    third = agent_turn(models, "check my notes too", memory, source)
    assert json.dumps(third["tools"]).startswith(json.dumps(first["tools"])[:-1])
    assert [item["function"]["name"] for item in third["tools"]][3:] == ["star_obsidian_search"]
    # Later prompts in any order, including one that names an older group again: no change.
    fourth = agent_turn(models, "which skill did you use?", memory, source)
    fifth = agent_turn(models, "ok", memory, source)
    assert json.dumps(fourth["tools"]) == json.dumps(fifth["tools"]) == json.dumps(third["tools"])
    assert memory.order == ["star_delegate", "star_skill_catalog", "star_skill_load", "star_obsidian_search"]


def test_without_stickiness_the_list_follows_each_prompt_as_before():
    source = Source({"skill": ["star_skill_catalog"]})
    for memory in (None, TurnMemory(sticky=False)):
        models = Models([reply("a"), reply("b")])
        first = agent_turn(models, "use a skill", memory, source)
        second = agent_turn(models, "thanks", memory, source)
        assert [item["function"]["name"] for item in first["tools"]] == ["star_delegate", "star_skill_catalog"]
        assert [item["function"]["name"] for item in second["tools"]] == ["star_delegate"]


def test_a_kept_tool_can_be_called_and_a_switched_off_source_drops_out_at_once():
    source = Source({"skill": ["star_skill_catalog"]})
    memory = TurnMemory(sticky=True)
    models = Models([reply("a"), reply(None, [tool_call("star_skill_catalog")]), reply("done"), reply("c")])
    agent_turn(models, "use a skill", memory, source)
    events = []
    agent_turn(models, "list them again", memory, source, on_event=events.append)   # no trigger word here
    assert source.calls == ["star_skill_catalog"]
    assert {"event": "tool_finished", "tool": "star_skill_catalog", "is_error": False} in events
    # The owner turns the source off: the remembered prompt selects nothing any more.
    source.enabled = False
    after = agent_turn(models, "and once more", memory, source)
    assert [item["function"]["name"] for item in after["tools"]] == ["star_delegate"]


def test_agent_turns_through_run_task_send_the_same_tool_bytes(desk):
    first = desk.turn("Use a skill and delegate research to a team of agents", "Done.", mode="agent")
    second = desk.turn("Thanks. What did you find?", "Nothing new.", mode="agent")
    assert len(first["tools"]) > 2
    assert json.dumps(second["tools"]) == json.dumps(first["tools"])
    assert second["messages"][0] == first["messages"][0]
    assert first["model"] == second["model"] == "star-fast"
    assert first["extra_body"]["id_slot"] == second["extra_body"]["id_slot"]


# ------------------------------------------------------------------ warm-up follows the last request

def test_the_warm_up_primes_the_shape_of_the_last_request(desk):
    scope = "STAR::chat::" + desk.chat
    # Before any message in an empty chat: plain chat on the quick model, nothing else.
    start = prefix_requests(desk.settings, desk.home, desk.chat)
    assert [(request["model"], request["tools"]) for request in start] == [("star-voice", None)]
    assert start[0]["messages"][0]["content"].startswith(FAST_RULES)
    # After an Agent turn: the tool prompt of that turn first, on its model and slot ...
    sent = desk.turn("Use a skill and delegate research to a team of agents", "Done.", mode="agent")
    after_agent = prefix_requests(desk.settings, desk.home, desk.chat)
    tools_first = after_agent[0]
    assert tools_first["model"] == "star-fast"
    assert json.dumps(tools_first["tools"]) == json.dumps(sent["tools"])
    assert tools_first["messages"][0] == sent["messages"][0] and RULES in tools_first["messages"][0]["content"]
    assert tools_first["extras"]["id_slot"] == sent["extra_body"]["id_slot"]
    # ... the finished exchange is now history, so the server reads it while the owner reads the answer.
    assert [message["role"] for message in tools_first["messages"]] == ["system", "user", "assistant", "user"]
    # ... and plain chat on the quick model second: another model, so it cannot replace the tool prompt.
    assert [(request["model"], request["tools"]) for request in after_agent[1:]] == [("star-voice", None)]
    # After a quick answer: the quick model first, then the main model reads the new exchange too,
    # so a Roblox or coding question later does not start by reading the whole conversation. The
    # main model last held this chat's tool prompt, so that is what is extended, not replaced.
    desk.turn("thanks!", [reply("Any time.", model="star-voice")])
    after_quick = prefix_requests(desk.settings, desk.home, desk.chat)
    assert [request["model"] for request in after_quick] == ["star-voice", "star-fast"]
    assert after_quick[0]["tools"] is None
    assert json.dumps(after_quick[1]["tools"]) == json.dumps(sent["tools"])
    assert after_quick[1]["messages"][0] == sent["messages"][0]
    assert turn_memory.last_shape(scope)["model"] == "star-voice"
    # A chat that only ever had plain turns is primed with plain chat on both models.
    other = desk.chats.new_chat("STAR")
    desk.chats.add("STAR", "user", "hello there", chat_id=other)
    desk.models.responses.append(reply("Hi!", model="star-voice"))
    desk.chats.add("STAR", "assistant", run_task(desk.settings, "hello there", chat_id=other, mode="fast"),
                   chat_id=other)
    plain = prefix_requests(desk.settings, desk.home, other)
    assert [(request["model"], request["tools"]) for request in plain] == [("star-voice", None), ("star-fast", None)]
    assert plain[0]["messages"] == plain[1]["messages"]                    # the same plain-chat request
    # After a restart (nothing remembered) a chat with earlier turns is primed on both models,
    # an empty chat on the quick model only (see the start of this test).
    turn_memory.forget()
    assert [(request["model"], request["tools"]) for request in
            prefix_requests(desk.settings, desk.home, desk.chat)] == [("star-voice", None), ("star-fast", None)]


def test_on_a_single_model_server_the_warm_up_after_a_tool_turn_skips_plain_chat(desk):
    server_roles.remember_models(LAN, [{"id": "star-fast"}])
    sent = desk.turn("Use a skill and delegate research to a team of agents", "Done.", mode="agent")
    requests = prefix_requests(desk.settings, desk.home, desk.chat)
    assert len(requests) == 1 and json.dumps(requests[0]["tools"]) == json.dumps(sent["tools"])
    # And never more than one request per model, whatever the last turn was.
    desk.turn("thanks!", "Any time.")
    turn_memory.forget()
    assert [(request["model"], request["tools"]) for request in
            prefix_requests(desk.settings, desk.home, desk.chat)] == [("star-fast", None)]


# ------------------------------------------------------------------ history budget

def test_history_budget_per_provider_kind():
    assert history_char_budget(lan_settings()) == 12000
    assert history_char_budget(Settings(model="m")) == 6000
    assert history_char_budget(Settings(provider="groq", model="m")) == 12000
    # A server with a small context gets half of what fits, never less than the floor.
    remember_server_limits(LAN, "star-fast", 4096, 2)
    assert history_char_budget(lan_settings()) == 3072
    assert history_char_budget(lan_settings(context_chars=6000)) == 3000


# ------------------------------------------------------------------ what the interface is told

def test_events_carry_only_a_clean_model_name():
    assert sanitize_event({"event": "model_answered", "model": "star-voice"})["activity"] == {
        "type": "model", "model": "star-voice"}
    assert sanitize_event({"event": "route_selected", "profile": "fast", "description": "Fast answer",
                           "model": "openai/gpt-oss-20b"})["activity"] == {
        "type": "route", "profile": "fast", "model": "openai/gpt-oss-20b"}
    assert sanitize_event({"event": "route_fallback", "model": "star-fast"})["activity"] == {
        "type": "route", "fallback": True, "model": "star-fast"}
    for bad in ("<img src=x>", "a b", "", None, 7, "x" * 200, "name\nnewline"):
        assert "model" not in sanitize_event({"event": "model_answered", "model": bad})["activity"]


# ------------------------------------------------------------------ voice hand-off

@pytest.fixture
def voice_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for name in ("STAR_SERVER_URL", "STAR_SERVER_API_KEY", "STAR_VOICE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    stored = {}
    # Like the real one: the environment variable first, then the (here: fake) OS keyring.
    monkeypatch.setattr(providers, "get_api_key", lambda name: __import__("os").environ.get(
        providers.KEY_ENV[name], "").strip() or stored.get(name) or None)
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(home=home, keyring=stored, env=monkeypatch)


def test_voice_reads_the_apps_settings_and_keyring_and_defaults_to_the_quick_model(voice_app):
    from star.voice.brain import BrainError, ServerBrain, server_configured, server_connection
    assert server_configured() is False
    with pytest.raises(BrainError, match="Settings"):
        ServerBrain.from_settings()
    lan_settings().save(voice_app.home / "settings.json")
    assert server_configured() is False                       # an address but no key yet
    voice_app.keyring["star_server"] = KEY
    assert server_configured() is True
    server_roles.remember_models(LAN, FLEET)                  # the app already asked the server
    brain = ServerBrain.from_settings(max_tokens=99)
    assert (brain.base_url, brain.model, brain.max_tokens) == (LAN, "star-voice", 99)
    assert KEY not in repr(vars(brain).get("base_url")) and KEY not in repr(brain)
    # A quick model the owner chose by hand wins over the server's.
    lan_settings(fast_model="my-quick").save(voice_app.home / "settings.json")
    assert server_connection()[2] == "my-quick"
    # No fleet on the server: the one configured model.
    server_roles.remember_models(LAN, [{"id": "only-model"}])
    lan_settings(model="only-model").save(voice_app.home / "settings.json")
    assert server_connection()[2] == "only-model"


def test_voice_environment_variables_still_override(voice_app):
    from star.voice.brain import ServerBrain, server_configured, server_connection
    lan_settings().save(voice_app.home / "settings.json")
    voice_app.keyring["star_server"] = KEY
    server_roles.remember_models(LAN, FLEET)
    voice_app.env.setenv("STAR_VOICE_MODEL", "star-other")
    assert server_connection()[:3] == (LAN, KEY, "star-other")
    voice_app.env.setenv("STAR_SERVER_URL", "http://192.168.1.30:9000/v1")
    voice_app.env.setenv("STAR_SERVER_API_KEY", "another-key-0123456789")
    brain = ServerBrain.from_settings()
    assert (brain.base_url, brain.model, brain.id_slot) == ("http://192.168.1.30:9000/v1", "star-other", None)
    assert brain._headers["Authorization"] == "Bearer another-key-0123456789"
    # With only the environment (no app settings at all) a call is still possible, as before.
    (voice_app.home / "settings.json").unlink()
    voice_app.keyring.clear()
    voice_app.env.delenv("STAR_VOICE_MODEL")
    assert server_configured() is True and server_connection()[2] == "star-fast"


def test_voice_asks_the_server_for_its_models_once_and_is_not_pinned(voice_app, monkeypatch):
    from star.voice import brain as voice_brain
    lan_settings().save(voice_app.home / "settings.json")
    voice_app.keyring["star_server"] = KEY
    asked = []

    def discover(endpoint, key, **_):
        asked.append(endpoint)
        server_roles.remember_models(endpoint, FLEET)
        remember_server_limits(endpoint, "star-voice", 16384, 2)
        return {}
    monkeypatch.setattr(server_roles, "discover", discover)
    assert voice_brain.server_configured() is True and asked == []          # the status check uses no network
    url, key, model, call_slot = voice_brain.server_connection()
    assert (url, key, model) == (LAN, KEY, "star-voice") and asked == [LAN]
    voice_brain.server_connection()
    assert asked == [LAN]                                                    # known now: not asked again
    # A call is background work: no slot is named, also while a typed chat is open on the quick
    # model, and the call changes nothing about that chat's slot.
    chat_slot = slot(lan_settings(), "STAR::chat::a", model="star-voice")
    assert chat_slot in (0, 1) and call_slot is None and voice_brain.server_connection()[3] is None
    assert slot(lan_settings(), "STAR::chat::a", model="star-voice") == chat_slot

    def sent_by(brain):
        sent = {}
        monkeypatch.setattr(brain._client, "stream", lambda method, address, **kw: sent.update(kw["json"]) or
                            (_ for _ in ()).throw(httpx.ConnectError("no server in a unit test")))
        with pytest.raises(httpx.ConnectError):             # the fake stops the request before it is sent
            brain.stream([{"role": "user", "content": "hi"}])
        return sent
    sent = sent_by(voice_brain.ServerBrain.from_settings())                  # what the app builds for a call
    assert "id_slot" not in sent and sent["model"] == "star-voice" and sent["cache_prompt"] is True
    # A caller that names a slot itself still gets it.
    assert sent_by(voice_brain.ServerBrain(url, key, model, id_slot=1))["id_slot"] == 1


def test_discover_reads_the_model_list_and_limits_of_loaded_models_only():
    seen = []
    roles = server_roles.discover(LAN, KEY, transport=fleet_server(seen))
    assert roles["quick"] == "star-voice" and server_roles.known(LAN)
    assert sorted(params["model"] for path, params in seen if path == "/props") == ["star-fast", "star-voice"]
    assert server_slots(lan_settings(), "star-quick") == 2
    assert server_roles.discover("http://192.168.1.21:8080/v1", KEY,
                                 transport=httpx.MockTransport(lambda request: httpx.Response(401))) == {}
