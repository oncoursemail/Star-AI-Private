"""Curiosity queue (star/curiosity.py, issue #555): the queue itself and the four places that fill it."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

import star.agent as agent
import star.desktop_core as core
from star import curiosity, doc_grounding, verify_ladder
from star.brain_router import GroundingPlan
from star.desktop_core import Settings, run_task

NOW = 1_790_000_000.0          # a fixed "now" for ranking (2026-09-21)


def stamp(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * 86400))


def write(path, *rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def event(kind, topic, days_ago=0.0, **extra):
    return {"ts": stamp(days_ago), "kind": kind, "key": curiosity.make_key(kind, topic), "topic": topic, "detail": "", **extra}


# --- the queue ----------------------------------------------------------------------------------------------------

def test_record_folds_repeats_and_ignores_case_spacing_and_digits(tmp_path):
    path = tmp_path / "q.jsonl"
    assert curiosity.record("weak_retrieval", "How do  I use Raycast 12 times", path=path)
    assert curiosity.record("weak_retrieval", "how do i use raycast 99 times", path=path)
    assert curiosity.record("unknown_answer", "how do i use raycast 99 times", path=path)   # another kind: another item
    items = curiosity.load(path)
    assert sorted((i.kind, i.count) for i in items.values()) == [("unknown_answer", 1), ("weak_retrieval", 2)]


def test_record_never_raises_and_refuses_bad_input(tmp_path, monkeypatch):
    path = tmp_path / "q.jsonl"
    assert not curiosity.record("not_a_kind", "something went wrong", path=path)
    assert not curiosity.record("weak_retrieval", "ab", path=path)
    assert not curiosity.record("weak_retrieval", "", path=path)
    assert not curiosity.record("weak_retrieval", "topic text", path=tmp_path)        # a folder: the write fails quietly
    monkeypatch.setenv("STAR_CURIOSITY", "off")
    assert not curiosity.record("weak_retrieval", "switched off topic", path=path)
    assert not path.exists()


def test_credentials_never_reach_the_file(tmp_path):
    path = tmp_path / "q.jsonl"
    fake = "abcdefghij" * 4                       # built here, so no key-shaped literal sits in the file
    curiosity.record("unknown_answer", "why does " + "api" + "_key = " + fake + " fail", path=path)
    assert "abcdefghij" not in path.read_text(encoding="utf-8")


def test_ranking_prefers_heavier_kinds_more_repeats_and_recent_events(tmp_path):
    path = tmp_path / "q.jsonl"
    rows = [event("weak_retrieval", "old but often", 40)] * 8 + [
        event("failed_verification", "fresh verification failure", 0),
        event("weak_retrieval", "fresh retrieval miss", 0),
        event("tool_failure", "tool star_x failed", 0)] + [event("tool_failure", "tool star_x failed", 0)] * 5
    write(path, *rows)
    ranked = [i.topic for i in curiosity.ranked(10, paths=(path,), now=NOW)]
    assert ranked[0] == "fresh verification failure"
    assert ranked.index("fresh retrieval miss") < ranked.index("old but often")
    assert "tool star_x failed" not in ranked            # counted, never studied
    assert curiosity.ranked(10, paths=(path,), now=NOW + 60 * 86400) == []      # everything expired


def test_studied_items_close_reopen_on_a_new_event_and_unteachable_ones_stop(tmp_path):
    path, done = tmp_path / "q.jsonl", tmp_path / "done.jsonl"
    topic = "new Roblox API members on Foo: Bar"
    key = curiosity.make_key("api_change", topic)
    real = time.time()
    write(path, {**event("api_change", topic), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(real - 3600))})
    assert [i.key for i in curiosity.ranked(5, paths=(path, done), now=real)] == [key]
    curiosity.resolve([key], "taught", "conductor-1", path=done)
    assert curiosity.ranked(5, paths=(path, done), now=real + 5) == []
    with path.open("a", encoding="utf-8") as handle:                      # it happens again after being studied
        handle.write(json.dumps({**event("api_change", topic), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(real + 60))}) + chr(10))
    assert [i.key for i in curiosity.ranked(5, paths=(path, done), now=real + 120)] == [key]
    other = curiosity.make_key("weak_retrieval", "nobody can teach this")
    write(path, {**event("weak_retrieval", "nobody can teach this"), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(real - 3600))})
    for tries in range(curiosity.MAX_TRIES + 1):
        assert [i.key for i in curiosity.ranked(5, paths=(path, done), now=real + 5)] == ([other] if tries < curiosity.MAX_TRIES else [])
        curiosity.resolve([other], "tried", path=done)
    with pytest.raises(ValueError):
        curiosity.resolve([key], "maybe", path=done)


def test_snapshot_goes_to_server_and_resolutions_come_back(tmp_path):
    app, server, done = tmp_path / "app.jsonl", tmp_path / "server.jsonl", tmp_path / "done.jsonl"
    write(app, event("weak_retrieval", "tween chains", 1), event("weak_retrieval", "tween chains", 0.5),
          event("tool_failure", "tool star_x failed", 0))
    server.write_bytes(curiosity.snapshot(path=app, now=NOW))
    shipped = curiosity.load(server)
    assert [(i.topic, i.count) for i in shipped.values()] == [("tween chains", 2)]       # tool failures stay home
    key = next(iter(shipped))
    curiosity.resolve([key], "taught", "conductor-1-abc", path=done)
    assert curiosity.merge_resolutions(done.read_text(encoding="utf-8"), path=app) == 1
    assert curiosity.merge_resolutions(done.read_text(encoding="utf-8"), path=app) == 0          # not twice
    assert curiosity.merge_resolutions('{"key": "../../x", "ts": "2026-01-01T00:00:00Z", "resolved": "taught"}', path=app) == 0
    assert curiosity.ranked(5, paths=(app,), now=NOW + 86400) == []


def test_a_full_file_is_compacted_instead_of_growing(tmp_path, monkeypatch):
    path = tmp_path / "q.jsonl"
    monkeypatch.setattr(curiosity, "MAX_BYTES", 2000)
    for _ in range(40):
        assert curiosity.record("weak_retrieval", "same topic over and over", path=path)
    assert path.stat().st_size < 4000                  # folded into one aggregate line at the limit
    assert [i.count for i in curiosity.load(path).values()] == [40]


@pytest.mark.parametrize("answer,flagged", [
    ("I don't know how that module works, sorry.", True),
    ("I couldn't find anything about that in the documentation.", True),
    ("I'm not sure whether this event exists.", True),
    ("Here is the script.\n```lua\n-- I don't know why this works\nprint(1)\n```", False),
    ("Use TweenService:Create(part, info, goal) and call :Play().", False),
])
def test_unknown_answers_are_recognised_outside_code(tmp_path, answer, flagged):
    path = tmp_path / "q.jsonl"
    assert curiosity.note_answer("How does the Foo module work?", answer, path=path) is flagged
    assert path.exists() is flagged


# --- the places that fill it (each fails without its hook) ---------------------------------------------------------

def queued():
    return {(i.kind, i.topic): i for i in curiosity.load().values()}


def test_a_failed_verification_is_queued_but_a_verified_fix_is_not(monkeypatch):
    records = [{"mistakes": [{"rung": "luau_check", "signature": "Unknown global 'Frobnicate'", "message": "m",
                              "verified": False},
                             {"rung": "unit_test", "signature": "expected 3 got 2", "message": "m", "verified": True}]}]
    assert verify_ladder.remember(records, task="write a thing") == 2
    assert [k for k in queued()] == [("failed_verification", "luau_check: Unknown global 'Frobnicate'")]


def test_empty_documentation_search_and_unknown_api_names_are_queued():
    class Docs:
        def __init__(self, found):
            self.found = found

        def search(self, query, **_):
            return [{"rank": 1, "title": "t", "heading": "h", "kind": "", "url": "", "source": "", "path": "",
                     "commit": "", "licence": "", "retrieved_at": "", "text": "x"}] if self.found else []

        def api_lookup(self, symbols):
            return [{"symbol": s, "found": False} for s in symbols]

    plan = GroundingPlan(retrieve="api", symbols=("Workspace:Frob",), passages=3, max_chars=2000)
    route = SimpleNamespace(grounding=plan)
    settings = SimpleNamespace()
    doc_grounding.prepare(settings, route, "How do I Frob the workspace?", client=Docs(found=False))
    kinds = {k[0] for k in queued()}
    assert kinds == {"weak_retrieval"}
    topics = " | ".join(topic for _, topic in queued())
    assert "Workspace:Frob" in topics and "Frob the workspace" in topics
    before = sum(i.count for i in curiosity.load().values())
    doc_grounding.prepare(settings, SimpleNamespace(grounding=doc_grounding.NO_GROUNDING), "hello", client=Docs(found=True))
    assert sum(i.count for i in curiosity.load().values()) == before          # a good retrieval adds nothing


def test_a_failed_tool_call_is_counted_by_tool_name():
    class Tool:
        def definitions(self, prompt):
            return [{"name": "test_read", "description": "d", "inputSchema": {"type": "object", "properties": {},
                                                                              "additionalProperties": False}}]

        def owns(self, name):
            return name == "test_read"

        def call(self, name, args, *, enabled):
            raise ValueError("no such fixture")

    def chunk(tool):
        parts = [SimpleNamespace(index=0, id="c1", function=SimpleNamespace(name="test_read", arguments="{}"))] if tool else []
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="" if tool else "done", tool_calls=parts))],
                               model="m", usage=None)

    class Stream:
        def __init__(self, items):
            self.items = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.items)
            except StopIteration:
                raise StopAsyncIteration

    sent = []

    class Completions:
        async def create(self, **kwargs):
            sent.append(kwargs)
            return Stream([chunk(True)] if len(sent) == 1 else [chunk(False)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    answer, *_ = asyncio.run(agent.execute(client=client, model="m", prompt="Read the fixture.", image_paths=[],
                                           intelligence=Tool(), stream_tokens=True, max_calls=2, on_event=lambda e: None))
    assert answer == "done"
    assert [(k, i.count) for k, i in queued().items()] == [(("tool_failure", "tool test_read failed"), 1)]


def test_a_chat_answer_that_says_it_does_not_know_is_queued(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    class Models:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="I don't know how the Frobnicator module works.", tool_calls=None))])

    class Client:
        chat = SimpleNamespace(completions=Models())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client())
    core.app_data().mkdir(parents=True, exist_ok=True)
    out = run_task(Settings(model="qwen-test"), "How does the Frobnicator module work in my game?", mode="fast")
    assert "Frobnicator" in out
    found = queued()
    assert list(found) == [("unknown_answer", "How does the Frobnicator module work in my game?")]
