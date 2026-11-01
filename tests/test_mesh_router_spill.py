"""Router admission for litha (server/mesh/router.py admission/admit): GPU queue first, a capped brain, fast 503s.

docs/agents/router-spill-20261029.md: on 10-29 litha requests spilled onto brain1's one-slot CPU model (88 in flight,
128 failures after 900 s). These tests pin the replacement behaviour against fake nodes and a fake brain.
"""
from __future__ import annotations

import asyncio
import json
import time

from tests.test_mesh_router import CHAT, Fake, call, mesh, run, setup

PLAIN = {**CHAT, "stream": False}


async def burst(port, n, body=PLAIN, headers=None):
    async def one():
        t0 = time.monotonic()
        status, hdrs, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", body, headers=headers)
        return status, hdrs, data, time.monotonic() - t0
    return await asyncio.gather(*(one() for _ in range(n)))


def test_brain_takes_at_most_its_cap_and_the_rest_get_a_fast_503(tmp_path):
    async def go():
        busy = Fake("star-pc", state="busy")
        brain = Fake("brain", tok_s=1.0, words=("slow",), first_delay=1.0)
        r, port, brain = await setup(tmp_path, [busy], brain=brain, queue_max_s=0.4)
        out = await burst(port, 3)
        ok = [o for o in out if o[0] == 200]
        busy503 = [o for o in out if o[0] == 503]
        assert len(ok) == 1 and ok[0][1]["X-Mesh-Backend"] == "brain1"
        assert len(busy503) == 2 and all(o[3] < 1.0 for o in busy503)       # failed fast, not after the brain
        assert b"mesh busy" in busy503[0][2] and busy503[0][1].get("Retry-After") == "5"
        assert len(brain.requests) == 1 and r.brain.inflight == 0 and r.waiting == []
        assert r.counters["admit_busy"] == 2
    run(go())


def test_busy_gpu_node_queues_in_the_router_and_never_spills_to_the_brain(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=60.0, words=("gpu",), first_delay=0.3)
        r, port, brain = await setup(tmp_path, [node], node_max_inflight=1)
        out = await burst(port, 4)
        assert [o[0] for o in out] == [200] * 4
        assert {o[1]["X-Mesh-Backend"] for o in out} == {"star-pc"} and not brain.requests
        assert len(node.requests) == 4 and r.nodes[0].inflight == 0
        waits = sorted(d.get("admit", {}).get("wait_ms", 0) for d in r.decisions)
        assert waits[0] == 0 and waits[-1] >= 600                     # the 4th waited for 3 answers ahead of it
    run(go())


def test_full_gpu_queue_past_queue_max_is_a_503_not_the_brain(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=60.0, words=("gpu",), first_delay=1.0)
        r, port, brain = await setup(tmp_path, [node], node_max_inflight=1, queue_max_s=0.3)
        out = await burst(port, 2)
        assert sorted(o[0] for o in out) == [200, 503] and not brain.requests
        d = [d for d in r.decisions if "busy" in d.get("admit", {})][0]
        assert d["admit"]["busy"] == "every GPU slot is busy" and d["outcome"].startswith("failed: mesh busy")
    run(go())


def test_cooling_node_is_waited_for_briefly_before_the_brain(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=60.0, words=("gpu",))
        r, port, brain = await setup(tmp_path, [node], gpu_wait_s=2.0)
        r.nodes[0].fail_until = time.monotonic() + 0.5
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 200 and headers["X-Mesh-Backend"] == "star-pc" and not brain.requests
        assert r.decisions[-1]["admit"]["wait_ms"] >= 400
        r.nodes[0].fail_until = time.monotonic() + 30          # longer than gpu_wait_s: the brain after the wait
        r.cfg["gpu_wait_s"] = 0.3
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1"
    run(go())


def test_no_node_at_all_goes_to_the_brain_without_waiting(tmp_path):
    async def go():
        r, port, brain = await setup(tmp_path, [Fake("owner-pc", state="busy")])
        t0 = time.monotonic()
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1" and time.monotonic() - t0 < 1.0
        assert "admit" not in r.decisions[-1]
    run(go())


def test_node_failure_falls_back_to_the_brain_only_while_it_has_room(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=60.0, http_status=500)
        r, port, brain = await setup(tmp_path, [node])
        r.brain.inflight = 1                                    # someone else holds the brain's litha slot
        status, _, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 500 and not brain.requests and r.decisions[-1]["errors"] == ["star-pc: HTTP 500"]
        r.nodes[0].fail_until = 0
        plan, _ = r.plan("litha")                               # the brain filled up after admission: still skipped
        assert [p[0].name for p in plan] == ["star-pc", "brain1", "brain1"]

        async def admitted(*_a):
            return plan
        r.admit = admitted
        try:
            await r.race(plan, "/chat/completions", lambda mid: json.dumps({**PLAIN, "model": mid}).encode(), "",
                         False, False, log := {"errors": []}, ("litha", None, True))
        except mesh.UpstreamError as e:
            assert e.status == 500
        assert log["errors"][1:] == ["brain1: litha slot busy (fallback skipped)"] * 2 and not brain.requests
        del r.admit
        r.brain.inflight, r.nodes[0].fail_until = 0, 0
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1"
    run(go())


def test_pass_through_models_neither_wait_nor_take_the_litha_brain_slot(tmp_path):
    async def go():
        brain = Fake("brain", tok_s=1.0, words=("slow",), first_delay=1.0)
        r, port, brain = await setup(tmp_path, [Fake("star-pc", state="busy")], brain=brain, queue_max_s=0.3)
        # a long star-fast answer on the brain (10-29 live: one hung for 900 s and blocked the litha slot)
        fast = asyncio.ensure_future(asyncio.to_thread(call, port, "POST", "/v1/chat/completions",
                                                       {**PLAIN, "model": "star-fast"}))
        await asyncio.sleep(0.3)
        assert r.brain_pass.inflight == 1 and r.brain.inflight == 0
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1"            # litha still gets the brain
        assert (await fast)[0] == 200 and r.brain_pass.inflight == 0
        assert sorted(q["model"] for q in brain.requests) == ["litha-26b", "star-fast"]
    run(go())


def test_admission_rules(tmp_path):
    async def go():
        node = Fake("star-pc", tok_s=60.0)
        r, port, brain = await setup(tmp_path, [node])
        plan, _ = r.plan("litha")
        assert [p[0].name for p in r.admission(plan, 0, True)[0]] == ["star-pc", "brain1", "brain1"]
        r.nodes[0].inflight = 2                                 # full: wait for the GPU, also past gpu_wait_s
        assert r.admission(plan, 50, True) == (None, "every GPU slot is busy", r.cfg["queue_max_s"])
        assert r.admission(plan, 0, "only")[2] == r.cfg["gpu_wait_s"]
        r.nodes[0].inflight = 0
        node.state = "busy"
        await r.poll_node(r.nodes[0])
        plan, _ = r.plan("litha", nodes="only")
        assert r.admission(plan, 0, "only") == (None, "no usable GPU node", 0.0)   # STAR's own lane: fail at once
        plan, _ = r.plan("litha")
        r.brain.inflight = 1
        assert r.admission(plan, 0, True)[1:] == ("no usable GPU node and brain1's litha slot is busy",
                                                  r.cfg["queue_max_s"])
        r.cfg["brain_litha_max_inflight"] = -1                  # no cap
        assert r.admission(plan, 0, True)[0][0][0] is r.brain
        r.brain.inflight = 0
    run(go())


def test_attempt_cancelled_before_it_ran_frees_its_slot(tmp_path):
    async def go():
        r, port, brain = await setup(tmp_path)
        t = r._start(r.brain, brain.url + "/v1", "/chat/completions", json.dumps(PLAIN).encode(), "", False)
        assert r.brain.inflight == 1
        t.cancel()
        await asyncio.gather(t, return_exceptions=True)
        assert r.brain.inflight == 0
    run(go())


def test_litha_on_the_brain_gives_its_slot_back_after_brain_litha_first_token_s(tmp_path):
    async def go():
        brain = Fake("brain", tok_s=1.0, words=("late",), first_delay=1.0)
        r, port, brain = await setup(tmp_path, [Fake("star-pc", state="busy")], brain=brain,
                                     brain_litha_first_token_s=0.3, brain_first_token_s=5.0)
        status, _, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", PLAIN)
        assert status != 200 and r.brain.inflight == 0
        assert r.decisions[-1]["errors"][0] == "brain1: no first token within 0 s"
        status, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions",
                                                     {**PLAIN, "model": "star-fast"})     # pass-through: 5 s limit
        assert status == 200 and headers["X-Mesh-Backend"] == "brain1"
    run(go())
