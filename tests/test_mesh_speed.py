"""Litha speed lab (server/mesh/speed/): parallel sections (skeleton, then expand)."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.speed import sections  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

SYSTEM = {"role": "system", "content": "You are Litha."}


def req(text, **kw):
    return {"model": "litha", "messages": [SYSTEM, {"role": "user", "content": text}], "stream": True,
            "max_tokens": 600, **kw}


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [p async for p in agen]


def test_eligible_needs_a_multi_part_streamed_question_without_code():
    assert sections.eligible(req("How do I make a shop button that gives a sword, with a LocalScript and a server Script?"))
    assert not sections.eligible(req("What is a variable?"))
    assert not sections.eligible(req("How do I make a shop and a GUI?", stream=False))
    assert not sections.eligible(req("Fix my shop script:\n```lua\nlocal x = 1\n```"))
    assert not sections.eligible({"messages": [SYSTEM]})


def test_parse_plan_strips_bullets_and_falls_back_on_one():
    assert sections.parse_plan("1. Short answer and server Script\n- The LocalScript\n* Next step\nextra") == [
        "Short answer and server Script", "The LocalScript", "Next step"]
    assert sections.parse_plan("ONE") == []
    assert sections.parse_plan("one.") == []
    assert sections.parse_plan("Only one line") == []
    assert sections.parse_plan("A\nB\nC\nD", max_parts=2) == ["A", "B"]


def test_part_bodies_keep_history_and_tell_each_writer_its_part():
    r = req("How do I make a shop?")
    b0 = sections.part_body(r, ["Server Script", "LocalScript"], 0, 300)
    b1 = sections.part_body(r, ["Server Script", "LocalScript"], 1, 300)
    assert b0["messages"][0] == SYSTEM and b0["max_tokens"] == 300 and b0["stream"] is True
    assert "Write ONLY part 1 (Server Script)" in b0["messages"][-1]["content"]
    assert "Start with the one or two sentence answer" in b0["messages"][-1]["content"]
    assert "Do not add a closing" in b0["messages"][-1]["content"]
    assert "Write ONLY part 2 (LocalScript)" in b1["messages"][-1]["content"]
    assert "End with one next step" in b1["messages"][-1]["content"]
    assert r["messages"][-1]["content"] == "How do I make a shop?"          # the request itself is untouched
    p = sections.plan_body(r)
    assert p["stream"] is False and p["temperature"] == 0.0 and p["max_tokens"] == 60


def test_ordered_streams_run_in_parallel_and_come_out_in_order():
    async def gen(name, n, delay):
        for i in range(n):
            await asyncio.sleep(delay)
            yield f"{name}{i}"

    async def go():
        t0 = time.perf_counter()
        out = await collect(sections.ordered([gen("a", 4, 0.05), gen("b", 4, 0.05)]))
        return out, time.perf_counter() - t0
    out, took = run(go())
    assert out == ["a0", "a1", "a2", "a3", "\n\n", "b0", "b1", "b2", "b3"]
    assert took < 0.33                                   # parallel: ~0.2 s, not 0.4 s


def test_ordered_raises_a_part_error_and_cancels_the_rest():
    async def bad():
        yield "x"
        raise RuntimeError("cut")

    async def slow():
        await asyncio.sleep(5)
        yield "never"

    async def go():
        out = []
        try:
            async for p in sections.ordered([bad(), slow()]):
                out.append(p)
        except RuntimeError as e:
            return out, str(e)
    t0 = time.perf_counter()
    assert run(go()) == (["x"], "cut")
    assert time.perf_counter() - t0 < 1


def test_answer_plans_then_expands_or_falls_back_to_one_stream():
    seen = []

    def fake(plan_text):
        async def complete(body):
            seen.append(("plan", body["messages"][-1]["content"]))
            return plan_text

        async def stream(body):
            seen.append(("part", body["messages"][-1]["content"]))
            yield f"<{len(seen)}>"
        return complete, stream

    stats = {}
    c, s = fake("Server Script\nLocalScript")
    out = run(collect(sections.answer(req("How do I make a shop?"), c, s, stats=stats)))
    assert stats["parts"] == ["Server Script", "LocalScript"]
    assert out[1] == "\n\n" and len(out) == 3
    assert sum(1 for k, _ in seen if k == "part") == 2

    seen.clear()
    c, s = fake("ONE")
    out = run(collect(sections.answer(req("What is a variable?"), c, s)))
    assert out == ["<2>"] and seen[1] == ("part", "What is a variable?")    # the plain request, unchanged


# ---- router hook (server/mesh/speed/hook.py via Router.complete) ---------------------------------------------------
sys.path.insert(0, str(ROOT / "tests"))
from test_mesh_router import Fake, call, setup, sse_text  # noqa: E402

SHOP = "How do I make a shop button that gives a sword, with a LocalScript and a server Script?"


def shop_chat(**kw):
    return {"model": "litha", "stream": True, "max_tokens": 400,
            "messages": [SYSTEM, {"role": "user", "content": SHOP}], **kw}


def test_router_answers_a_multi_part_question_as_plan_plus_parallel_parts(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=45.0, words=("Server part", "\n", "Client part"))
        r, port, brain = await setup(tmp_path, [node], sections=True, sections_nodes=["owner-pc"])
        st, hdr, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", shop_chat())
        return st, hdr, data, node, brain, r
    st, hdr, data, node, brain, r = run(go())
    assert st == 200 and hdr["X-Mesh-Backend"] == "owner-pc" and hdr["X-Mesh-Sections"] == "2"
    assert sse_text(data) == "Server part\nClient part\n\nServer part\nClient part"
    assert data.rstrip().endswith(b"data: [DONE]") and b'"finish_reason": "stop"' in data
    plan = [q for q in node.requests if not q.get("stream")]
    parts = [q for q in node.requests if q.get("stream")]
    assert len(plan) == 1 and plan[0]["max_tokens"] == 60 and plan[0]["model"] == "litha-fast"
    assert len(parts) == 2 and any("Write ONLY part 2 (Client part)" in q["messages"][-1]["content"] for q in parts)
    assert not brain.requests and r.decisions[-1]["outcome"] == "ok" and r.decisions[-1]["parts"] == 2


def test_router_sections_off_unlisted_node_or_simple_question_use_one_stream(tmp_path):
    async def go(cfg, body):
        node = Fake("owner-pc", tok_s=45.0, words=("Hi", " there"))
        r, port, brain = await setup(tmp_path, [node], **cfg)
        st, hdr, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", body)
        return hdr, node
    for cfg, body in (({}, shop_chat()),
                      ({"sections": True, "sections_nodes": ["other"]}, shop_chat()),
                      ({"sections": True, "sections_nodes": ["owner-pc"]},
                       {**shop_chat(), "messages": [SYSTEM, {"role": "user", "content": "What is a variable?"}]})):
        hdr, node = run(go(cfg, body))
        assert "X-Mesh-Sections" not in hdr and len(node.requests) == 1 and node.requests[0]["stream"]


def test_router_plan_of_one_streams_the_plain_request_through_sections(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=45.0, words=("ONE",))
        r, port, brain = await setup(tmp_path, [node], sections=True, sections_nodes=["owner-pc"])
        return await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", shop_chat()), node
    (st, hdr, data), node = run(go())
    assert hdr["X-Mesh-Sections"] == "1" and sse_text(data) == "ONE"
    assert node.requests[-1]["messages"][-1]["content"] == SHOP


def test_router_sections_failing_before_the_first_word_falls_back_to_the_normal_path(tmp_path):
    async def go():
        node = Fake("owner-pc", tok_s=45.0, http_status=500)
        r, port, brain = await setup(tmp_path, [node], sections=True, sections_nodes=["owner-pc"])
        st, hdr, data = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", shop_chat())
        return st, hdr, data, r
    st, hdr, data, r = run(go())
    assert st == 200 and hdr["X-Mesh-Backend"] == "brain1" and sse_text(data) == "Brain here"
    assert any("single stream" in (d.get("outcome") or "") for d in r.decisions)


# ---- node ladder steps with extra args (server/mesh/node/node_agent.py) ----------------------------------------------
def test_ladder_step_can_add_a_draft_model_and_lower_steps_do_not(tmp_path):
    sys.path.insert(0, str(ROOT / "server" / "mesh" / "node"))
    import node_agent as na  # noqa: PLC0415
    (tmp_path / "engine").mkdir()
    (tmp_path / "models").mkdir()
    for f in ("engine/llama-server.exe", "models/m.gguf", "models/mtp.gguf"):
        (tmp_path / f).write_bytes(b"x")
    cfg = {**na.DEFAULTS, "llama_server": "engine/llama-server.exe", "model_path": "models/m.gguf",
           "llama_args": ["-ngl", "99", "-fa", "on"], "vram_reserve_mb": 150,
           "ngl_ladder": [[100, 7300, ["--model-draft", "models/mtp.gguf", "--spec-type", "draft-mtp"]],
                          [99, 7000], [47, 6780]]}
    assert na.pick_ngl(cfg, 7500) == 100 and na.pick_ngl(cfg, 7200) == 99 and na.pick_ngl(cfg, 7000) == 47
    top = na.llama_argv(cfg, tmp_path, 100)
    assert top[top.index("-ngl") + 1] == "100"
    assert top[top.index("--model-draft") + 1] == str(tmp_path / "models" / "mtp.gguf") and "draft-mtp" in top
    plain = na.llama_argv(cfg, tmp_path, 99)
    assert "--model-draft" not in plain and plain[plain.index("-ngl") + 1] == "99"
    (tmp_path / "models" / "mtp.gguf").unlink()             # no draft file: the step loads plain (all layers)
    bare = na.llama_argv(cfg, tmp_path, 100)
    assert "--model-draft" not in bare and "--spec-type" not in bare and bare[bare.index("-ngl") + 1] == "100"


def test_ladder_steps_can_name_a_shared_arg_set_and_kvu_keeps_the_full_context(tmp_path):
    sys.path.insert(0, str(ROOT / "server" / "mesh" / "node"))
    import node_agent as na  # noqa: PLC0415
    (tmp_path / "models").mkdir()
    for f in ("llama-server.exe", "models/m.gguf", "models/mtp.gguf"):
        (tmp_path / f).write_bytes(b"x")
    cfg = {**na.DEFAULTS, "llama_server": "llama-server.exe", "model_path": "models/m.gguf", "ctx": 6144,
           "llama_args": ["-ngl", "99", "-np", "2", "-kvu"], "vram_reserve_mb": 150,
           "step_args": {"mtp": ["--model-draft", "models/mtp.gguf", "--spec-type", "draft-mtp"]},
           "ngl_ladder": [[99, 7300, "mtp"], [46, 6800, "mtp"], [40, 5900]]}
    assert na.pick_ngl(cfg, 7000) == 46
    a46 = na.llama_argv(cfg, tmp_path, 46)
    assert a46[a46.index("-ngl") + 1] == "46" and a46[a46.index("--model-draft") + 1] == str(tmp_path / "models" / "mtp.gguf")
    assert "--model-draft" not in na.llama_argv(cfg, tmp_path, 40)
    assert na.slot_ctx(cfg) == 6144                                   # -kvu: every slot may use the whole pool
    assert na.slot_ctx({**cfg, "llama_args": ["-np", "2"]}) == 3072


def test_ladder_prefers_draft_with_fewer_layers_and_steps_down_by_position_even_with_a_repeated_ngl(tmp_path):
    from test_mesh_node import Proc, make, na  # noqa: PLC0415
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / "mtp.gguf").write_bytes(b"x")
    mtp = ["--model-draft", "models/mtp.gguf", "--spec-type", "draft-mtp"]
    ladder = [[100, 7400, "mtp"], [47, 7170, "mtp"], [99, 7130], [46, 7050, "mtp"], [47, 6900], [44, 6560]]
    node, gpu, clock, procs = make(tmp_path, ngl_ladder=ladder, step_args={"mtp": mtp}, llama_args=["-ngl", "99"],
                                   other_vram_grow_mb=99999, min_free_loaded_mb=100, vram_reserve_mb=150)
    assert [na.pick_step(node.config, f) for f in (7600, 7330, 7290, 7210, 7060, 6720, 6000)] == [0, 1, 2, 3, 4, 5, -1]
    own = {i: s[1] for i, s in enumerate(ladder)}

    def popen(argv, **kw):
        procs.append((argv, kw))
        gpu["used"] = 8192 - 7330 + own[node.step]          # desktop leaves 7330 MB free -> step 1 (47 + draft)
        return Proc()
    node._popen = popen
    gpu["used"] = 8192 - 7330
    node.tick()
    argv = procs[-1][0]
    assert node.step == 1 and argv[argv.index("-ngl") + 1] == "47" and "--model-draft" in argv
    gpu["used"] = 8192 - 10                                  # the launcher grew: 10 MB free while loaded
    node.tick()                                              # 10 + 7170 freed -> step 4 (plain 47, same -ngl)
    argv = procs[-1][0]
    assert node.step == 4 and len(procs) == 2 and argv[argv.index("-ngl") + 1] == "47" and "--model-draft" not in argv
    assert na.step_label(node.config, 1) == "ngl 47 + draft" and na.step_label(node.config, 4) == "ngl 47"


def test_step_label_names_ffn_layers_kept_on_the_cpu():
    from test_mesh_node import na  # noqa: PLC0415
    cfg = {"ngl_ladder": [[99, 7210, "mtp"], [99, 7040, "mtp_ffn2"], [46, 6900]],
           "step_args": {"mtp": ["--model-draft", "m.gguf"], "mtp_ffn2": ["--model-draft", "m.gguf", "-ncffn", "2"]}}
    assert [na.step_label(cfg, i) for i in range(3)] == ["ngl 99 + draft", "ngl 99 + draft, 2 FFN on CPU", "ngl 46"]
