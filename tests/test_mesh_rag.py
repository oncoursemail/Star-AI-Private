"""Mesh router recall second stage (intent guard, the live model as judge) and grounding on verified answers
(server/mesh/instant.py + router.py), with fake embeddings and a fake judge."""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))

from mesh import instant  # noqa: E402
from test_mesh_instant import DOOR, DOOR_ANSWER, SYSTEM, add, chat, post, setup  # noqa: E402
from test_mesh_router import Fake, run, sse_text  # noqa: E402

TOUCH = "How do I make a door in Roblox open when a player touches it?"
TOUCH_ANSWER = "Use **Touched** in a server Script.\n\n```lua\nscript.Parent.Touched:Connect(function(hit) end)\n```"


TOUCH_VEC = [0.6, 0.8, 0.0]


def at(sim_a: float, sim_b: float | None = None) -> list[float]:
    """A unit vector with cosine sim_a to the DOOR entry ([1, 0, 0]) and sim_b to the TOUCH entry (TOUCH_VEC)."""
    y = 0.0 if sim_b is None else (sim_b - 0.6 * sim_a) / 0.8
    rest = 1.0 - sim_a * sim_a - y * y
    assert rest >= 0
    return [sim_a, y, math.sqrt(rest)]


async def rag_setup(tmp_path, vectors: dict, pick=None, judge_delay=0.0, node_delay=0.0, **cfg):
    """Router with the DOOR and TOUCH entries; embeddings from `vectors` (text -> vector), judge answers `pick`
    ((number, probability) or None = no idle node) after `judge_delay` seconds."""
    node = Fake("node-a", tok_s=30.0, words=("live",), first_delay=node_delay)
    r, port, brain, _ = await setup(tmp_path, [node], cache_threshold=0.95, **cfg)
    base = {DOOR: [1.0, 0.0, 0.0], TOUCH: TOUCH_VEC, **vectors}

    async def fake_embed(text):
        return base.get(text, [0.0, 0.0, 1.0])
    r.embed = fake_embed
    r.judge_calls = []

    async def fake_judge(query, docs):
        r.judge_calls.append((query, docs))
        await asyncio.sleep(judge_delay)
        return pick
    r.judge = fake_judge
    assert (await add(port))[0] == 200
    assert (await add(port, question=TOUCH, answer=TOUCH_ANSWER))[0] == 200
    return r, port, node


# ---- pure helpers -----------------------------------------------------------------------------------------------------
def test_intent_guard_finds_direction_and_language_conflicts():
    c2s = "How do I use a RemoteEvent in Roblox to send a message from a LocalScript to the server?"
    assert instant.intent_conflict("roblox remote event from server to client", c2s) == "direction"
    assert instant.intent_conflict("roblox FireClient example", c2s) == "direction"
    assert instant.intent_conflict("send something from local script to server roblox", c2s) is None
    assert instant.intent_conflict("for loop in lua", "how do I write a for loop in python") == "language"
    assert instant.intent_conflict("unity C# jump script", "unity jump in javascript") == "language"
    assert instant.intent_conflict("bedrock edition command block", "java edition command block") == "edition"
    assert instant.intent_conflict("how do i make a door open with e", DOOR) is None
    assert instant.intent_conflict("unity jump", "unity c# jump script") is None      # one side names nothing


def test_judge_pick_needs_a_confident_digit():
    lp = lambda *pairs: [{"token": t, "logprob": math.log(p)} for t, p in pairs]   # noqa: E731
    assert instant.judge_pick(lp(("1", 0.97), ("0", 0.02)), 4, 0.8) == (1, 0.97)
    k, p = instant.judge_pick(lp(("2", 0.6), ("1", 0.35)), 4, 0.8)
    assert k == 0 and abs(p - 0.6) < 1e-9                                      # unsure: no hit
    assert instant.judge_pick(lp(("0", 0.99)), 4, 0.8)[0] == 0                 # "none of them"
    assert instant.judge_pick(lp((" 3", 0.5), ("3", 0.45)), 4, 0.8)[0] == 3    # same digit, two spellings
    assert instant.judge_pick(lp(("5", 0.99)), 4, 0.8)[0] == 0                 # not a candidate number
    assert instant.judge_pick(lp(("Yes", 0.99)), 4, 0.8) == (0, 0.0) and instant.judge_pick(None, 4, 0.8)[0] == 0
    msgs = instant.judge_messages("door opens with e roblox", [DOOR, TOUCH])
    assert msgs[0]["role"] == "system" and f"1. {DOOR}\n2. {TOUCH}" in msgs[1]["content"]
    assert "door opens with e roblox" in msgs[1]["content"] and "or 0" in msgs[1]["content"]


def test_candidates_are_items_with_canonical_question_and_page_platform(tmp_path):
    c = instant.AnswerCache(str(tmp_path / "a.db"))
    c.put(DOOR, DOOR_ANSWER, "", "s", 1.0, [1.0, 0.0, 0.0], 3600)
    c.put("door press e roblox", DOOR_ANSWER, "", "s", 1.0, [0.9, 0.1, 0.0], 3600)          # same item
    c.put("make door open press e", DOOR_ANSWER, "roblox", "s", 1.0, [0.95, 0.0, 0.05], 3600)  # page entry
    c.put(TOUCH, TOUCH_ANSWER, "", "s", 1.0, [0.0, 1.0, 0.0], 3600)
    cands = c.candidates([0.9, 0.2, 0.0], "roblox", "door opens on e")
    assert [x["canon"] for x in cands] == [DOOR, TOUCH]                        # one row per answer, canonical first
    assert cands[0]["question"] == "door press e roblox"                       # the closest phrasing of it
    # an entry seeded for the Roblox page answers a Roblox-page question that names no platform (it used to be
    # filtered out: its question names no platform, the page does)
    only_page = c.candidates([0.95, 0.0, 0.05], "roblox", "make door open press e", k=4)
    assert only_page[0]["question"] == "make door open press e" and only_page[0]["sim"] > 0.99
    assert c.candidates([0.95, 0.0, 0.05], "", "make door open press e") == []  # no page: no platform known
    assert c.candidates([1.0, 0.0, 0.0], "", "door in unity press e") == []     # other platform
    c.delete(1)                                                                # the next phrasing becomes canonical
    assert c.candidates([1.0, 0.0, 0.0], "roblox", "door e")[0]["canon"] == "door press e roblox"
    assert instant.AnswerCache(str(tmp_path / "a.db")).canon == c.canon         # same after a restart


def test_ground_question_only_for_a_plain_first_question():
    page = {"role": "system", "content": "You are Litha.\n\nLauncher context: Roblox page." + "x" * 5000}
    assert instant.ground_question({"messages": [page, {"role": "user", "content": DOOR}]}) == DOOR
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]
    for msgs in ([SYSTEM, *hist, {"role": "user", "content": DOOR}],                     # a follow-up
                 [SYSTEM, {"role": "user", "content": DOOR + "\n```lua\nlocal d = 1\n```"}],  # the user's code
                 [SYSTEM, {"role": "user", "content": "Why does my door script give an error on line 4?"}],
                 [SYSTEM, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}],
                 [SYSTEM]):
        assert instant.ground_question({"messages": msgs}) is None, msgs
    assert instant.ground_question({"messages": [SYSTEM, {"role": "user", "content": DOOR}],
                                    "tools": [{"type": "function"}]}) is None


def test_grounded_messages_put_marked_references_before_the_question_only():
    msgs = [SYSTEM, {"role": "user", "content": "door that opens with e"}]
    out = instant.grounded_messages(msgs, [{"question": DOOR, "answer": DOOR_ANSWER + "\n"}])
    assert out[0] == SYSTEM and msgs[1]["content"] == "door that opens with e"    # system untouched, input not changed
    text = out[1]["content"]
    assert text.startswith(instant.GROUND_HEAD) and "never copy blindly" in text
    assert f"[Q] {DOOR}\n[A] {DOOR_ANSWER}\n\n---\nQuestion: door that opens with e" in text


# ---- router: grey zone -------------------------------------------------------------------------------------------------
def test_grey_zone_hit_when_the_judge_picks_a_candidate(tmp_path):
    async def go():
        para, q2 = "door roblox that opens if you press e", "roblox door that opens when you walk into it"
        r, port, node = await rag_setup(tmp_path, {para: at(0.90, 0.30), q2: at(0.87, 0.89)}, pick=(1, 0.97),
                                        node_delay=0.3)
        status, h, data = await post(port, "/v1/chat/completions", chat(para))
        assert h["X-Mesh-Cache"] == "hit" and h["X-Mesh-Cache-Match"] == "semantic" and sse_text(data) == DOOR_ANSWER
        assert h["X-Mesh-Cache-Stage2"] == "judge: 1 (0.97)" and float(h["X-Mesh-Cache-Similarity"]) < 0.95
        assert r.judge_calls == [(para, [DOOR, TOUCH])]                        # canonical questions, best first
        assert r.counters["cache_judge_hit"] == 1

        async def second(query, docs):                                         # the judge may pick candidate 2
            assert docs == [TOUCH, DOOR]                                       # when it is above the floor too
            return 2, 0.9
        r.judge = second
        _, h, data = await post(port, "/v1/chat/completions", chat(q2))
        assert h["X-Mesh-Cache"] == "hit" and sse_text(data) == DOOR_ANSWER    # DOOR: candidate 2 at 0.87
    run(go())


def test_grey_zone_misses_when_judge_says_none_is_unsure_or_below_the_floor(tmp_path):
    async def go():
        q1, q2, q3 = "roblox door that opens with a keypad code", "roblox door", "roblox door with a lever"
        r, port, node = await rag_setup(tmp_path, {q1: at(0.90, 0.30), q2: at(0.70), q3: at(0.88, 0.80)},
                                        pick=(0, 0.95))
        _, h, data = await post(port, "/v1/chat/completions", chat(q1))
        assert h["X-Mesh-Cache"] == "miss" and sse_text(data) == "live"
        assert r.decisions[-1]["cache_stage2"] == "judge: none (0.95)"
        _, h, data = await post(port, "/v1/chat/completions", chat(q2, mesh_ground=False))
        assert h["X-Mesh-Cache"] == "miss" and len(r.judge_calls) == 1          # 0.70 < floor: no judge call

        async def judge_touch(query, docs):
            return 2, 0.99                                                     # TOUCH: 0.80 < judge_floor
        r.judge = judge_touch
        _, h, _ = await post(port, "/v1/chat/completions", chat(q3, mesh_ground=False))
        assert h["X-Mesh-Cache"] == "miss" and r.decisions[-1]["cache_stage2"] == "judge: 2 below floor"
    run(go())


def test_intent_guard_blocks_even_above_the_threshold(tmp_path):
    async def go():
        c2s = "How do I use a RemoteEvent in Roblox to send a message from a LocalScript to the server?"
        s2c = "roblox remote event from server to client"
        r, port, node = await rag_setup(tmp_path, {c2s: [0.0, 0.0, 1.0], s2c: [0.0, 0.1, 0.995]}, pick=(1, 0.99))
        assert (await add(port, question=c2s, answer="Use FireServer."))[0] == 200
        _, h, data = await post(port, "/v1/chat/completions", chat(s2c))           # cosine 0.995 >= 0.95
        assert h["X-Mesh-Cache"] == "miss" and sse_text(data) == "live" and not r.judge_calls
        assert r.decisions[-1]["cache_stage2"] == "intent: direction" and r.counters["cache_intent_blocked"] == 1
        assert node.requests[-1]["messages"][-1]["content"] == s2c                 # no reference across the conflict
    run(go())


def test_no_idle_node_means_no_grey_zone_hit(tmp_path):
    async def go():
        para = "door roblox that opens if you press e"
        r, port, node = await rag_setup(tmp_path, {para: at(0.90)}, pick=None)
        _, h, data = await post(port, "/v1/chat/completions", chat(para, mesh_ground=False))
        assert h["X-Mesh-Cache"] == "miss" and r.decisions[-1]["cache_stage2"] == "judge: no idle node"
    run(go())


def test_slow_judge_costs_a_miss_at_most_the_hold_time(tmp_path):
    async def go():
        para = "door roblox that opens if you press e"
        r, port, node = await rag_setup(tmp_path, {para: at(0.90)}, pick=(1, 0.99), judge_delay=1.0,
                                        cache_hold_s=0.15)
        t0 = time.monotonic()
        _, h, data = await post(port, "/v1/chat/completions", chat(para, mesh_ground=False))
        assert sse_text(data) == "live" and h["X-Mesh-Cache-Ms"] == "late"
        assert time.monotonic() - t0 < 0.6
    run(go())


def test_lookup_finishing_inside_the_hold_still_serves_the_cache(tmp_path):
    async def go():
        para = "door roblox that opens if you press e"
        r, port, node = await rag_setup(tmp_path, {para: at(0.90)}, pick=(1, 0.99), judge_delay=0.08,
                                        cache_hold_s=0.3)
        _, h, data = await post(port, "/v1/chat/completions", chat(para, mesh_ground=False))
        assert h["X-Mesh-Cache"] == "hit" and sse_text(data) == DOOR_ANSWER
        await asyncio.sleep(0.05)
        assert r.nodes[0].inflight == 0                                        # the started backend was released
    run(go())


def test_judge_asks_the_idle_node_for_one_token(tmp_path):
    async def go():
        node = Fake("node-a", tok_s=30.0, words=("2",))
        r, port, brain, _ = await setup(tmp_path, [node])
        assert await r.judge("q", [DOOR, TOUCH]) == (2, 1.0)                   # no logprobs: the token counts
        req = node.requests[-1]
        assert req["max_tokens"] == 1 and req["temperature"] == 0 and req["logprobs"] is True
        assert req["model"] == "litha-fast" and req["messages"] == instant.judge_messages("q", [DOOR, TOUCH])
        assert r.nodes[0].inflight == 0
        node.state = "busy"
        await r.poll_node(r.nodes[0])
        assert await r.judge("q", [DOOR]) is None and not brain.requests        # never the brain
    run(go())


# ---- router: grounding -------------------------------------------------------------------------------------------------
def test_grounding_attaches_close_verified_answers_on_a_miss(tmp_path):
    async def go():
        q = "roblox door that opens with a lever"
        r, port, node = await rag_setup(tmp_path, {q: at(0.86, 0.83)}, pick=(0, 0.9))
        _, h, data = await post(port, "/v1/chat/completions", chat(q))
        assert h["X-Mesh-Cache"] == "miss" and h["X-Mesh-Ground"] == "2" and sse_text(data) == "live"
        msgs = node.requests[-1]["messages"]
        assert msgs[0] == SYSTEM and len(msgs) == 2 and "mesh_ground" not in node.requests[-1]
        text = msgs[-1]["content"]
        assert text.startswith(instant.GROUND_HEAD) and text.endswith("Question: " + q)
        assert text.index(DOOR) < text.index(TOUCH) and DOOR_ANSWER in text and TOUCH_ANSWER in text
        assert r.decisions[-1]["ground"] == h["X-Mesh-Ground-Ids"] and r.counters["ground_used"] == 1
    run(go())


def test_no_grounding_below_the_floor_for_user_code_or_when_switched_off(tmp_path):
    async def go():
        far, near = "how do i make a sword", "roblox door that opens with a lever"
        r, port, node = await rag_setup(tmp_path, {far: at(0.5), near: at(0.86)}, pick=(0, 0.9))
        hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]
        code = near + "\n```lua\nlocal door = script.Parent\n```"
        cases = [(chat(far), "0"), (chat(near, mesh_ground=False), None), (chat(near, history=hist), None),
                 (chat(code), None)]
        for body, want in cases:
            _, h, _ = await post(port, "/v1/chat/completions", body)
            assert h.get("X-Mesh-Ground") == want, (body["messages"][-1], h)
            assert not node.requests[-1]["messages"][-1]["content"].startswith(instant.GROUND_HEAD)
        _, h, _ = await post(port, "/v1/chat/completions", chat(near), headers={"X-Mesh-Ground": "off"})
        assert "X-Mesh-Ground" not in h
    run(go())


def test_grounding_with_page_context_and_a_slow_embedding(tmp_path):
    async def go():
        q = "door that opens with a lever"
        page = {"role": "system", "content": "You are Litha. " + "Roblox page. " * 400}    # > cache system limit
        r, port, node = await rag_setup(tmp_path, {q: at(0.86)}, pick=(0, 0.9))
        body = {"model": "litha", "stream": True, "mesh_context": "roblox",
                "messages": [page, {"role": "user", "content": q}]}
        _, h, _ = await post(port, "/v1/chat/completions", body)
        assert h["X-Mesh-Cache"] == "skip" and h["X-Mesh-Ground"] == "1"            # no cache, still grounded
        assert node.requests[-1]["messages"][0] == page

        async def slow_embed(text):
            await asyncio.sleep(1.0)
            return at(0.86)
        r.embed = slow_embed
        t0 = time.monotonic()
        _, h, data = await post(port, "/v1/chat/completions", chat("roblox " + q))
        assert h["X-Mesh-Ground"] == "late" and sse_text(data) == "live"
        assert time.monotonic() - t0 < 0.8 and node.requests[-1]["messages"][-1]["content"] == "roblox " + q
    run(go())


def test_long_verified_answers_are_not_attached(tmp_path):
    async def go():
        q = "roblox door that opens with a lever"
        r, port, node = await rag_setup(tmp_path, {q: at(0.86, 0.83)}, pick=(0, 0.9), ground_max_chars=len(DOOR_ANSWER))
        _, h, _ = await post(port, "/v1/chat/completions", chat(q))
        text = node.requests[-1]["messages"][-1]["content"]
        assert h["X-Mesh-Ground"] == "1" and DOOR_ANSWER in text and TOUCH_ANSWER not in text
        assert json.loads(json.dumps(r.status()))["instant"]["ground"]["ground_max"] == 2
    run(go())


def test_no_grounding_when_the_answer_goes_to_the_brain(tmp_path):
    async def go():
        q = "roblox door that opens with a lever"
        r, port, node = await rag_setup(tmp_path, {q: at(0.86)}, pick=(0, 0.9))
        node.state = "busy"
        await r.poll_node(r.nodes[0])
        brain = r.brain
        _, h, data = await post(port, "/v1/chat/completions", chat(q))
        assert h["X-Mesh-Backend"] == brain.name and "X-Mesh-Ground" not in h
        assert r.counters["ground_skipped_brain"] == 1
    run(go())
