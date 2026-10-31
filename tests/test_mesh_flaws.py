"""Flaw loop (server/mesh/flaws): turn signals and fix rules, shipped.json reload, the router hook, graders, the miner's
clusters, the A/B decision and the rollback watch."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.flaws import gate, hook, items, mine, route  # noqa: E402
sys.path.remove(str(ROOT / "server"))

DOOR = "```lua\nlocal door = script.Parent\nlocal p = Instance.new(\"ProximityPrompt\", door)\np.Triggered:Connect(function() door.CanCollide = false end)\n```"


def chat(*turns):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(turns)]


def test_followup_in_a_coding_chat_is_code_but_a_new_question_is_not():
    sig = hook.signals(chat("make a door that opens when i press e", DOOR, "now make it close after 3 seconds"))
    assert {"codectx", "followup"} <= set(sig["flags"]) and "code-followup" in hook.eligible(sig)
    new = hook.signals(chat("make a door that opens when i press e", DOOR, "how far away is the moon"))
    assert "code-followup" not in hook.eligible(new)
    general = hook.signals(chat("whats the hottest planet", "Venus.", "what about the coldest one"))
    assert "codectx" not in general["flags"] and hook.eligible(general) == []


def test_reask_and_repeat_flags():
    sig = hook.signals(chat("make a coin that gives +1", DOOR, "it says attempt to index nil with Coins"))
    assert "reask" in sig["flags"] and "reask-note" in hook.eligible(sig)
    rep = hook.signals(chat("how do i make a door open with e", "Sure...", "how do i make a door open with e key"))
    assert "repeat" in rep["flags"]


def test_game_build_without_engine_word_and_general_lookalikes():
    assert "game-build" in hook.eligible(hook.signals(chat("make door open press e")))
    assert "game-build" in hook.eligible(hook.signals(chat("how do i save a table in a datastore")))
    for q in ("how do i make friends at a new school", "help me write a story about a player who wins",
              "how do I bake cookies", "what is the capital of France?"):
        assert "game-build" not in hook.eligible(hook.signals(chat(q))), q


def test_soft_safety_never_touches_real_safety():
    assert "soft-safety" in hook.eligible(hook.signals(chat("how do i make a secret door that opens when you touch a button")))
    for q in ("this kid in my roblox game says if i tell him my password he will give me items. should i do it?",
              "a guy i met in a game keeps asking me to send him pics. he says its our little secret",
              "a player keeps asking for my address in chat"):
        assert "soft-safety" not in hook.eligible(hook.signals(chat(q))), q


def test_safety_word_inside_another_word():
    assert hook.eligible(hook.signals(chat("how does photosynthesis work"))) == ["safety-substring"]
    assert hook.eligible(hook.signals(chat("i found some pills in the park can i eat one"))) == []
    assert hook.eligible(hook.signals(chat("i swallowed something poisonous"))) == []


def test_apply_respects_shipped_and_override(tmp_path):
    cfg = {"flaws": True, "flaws_dir": str(tmp_path), "flaws_samples": True}
    msgs = chat("make a door that opens when i press e", DOOR, "it doesnt work nothing happens")
    req = {"messages": [dict(m) for m in msgs]}
    entry = hook.apply(req, {}, cfg)
    assert "mesh_general" not in req and set(entry["would"]) == {"code-followup", "reask-note"} and "fire" not in entry
    sample = json.loads((tmp_path / "samples.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert sample["id"] == entry["id"] and sample["msgs"][-1]["content"] == "it doesnt work nothing happens"
    (tmp_path / "shipped.json").write_text(json.dumps({"fixes": {"reask-note": {}}}), encoding="utf-8")
    hook.SHIPPED.checked = 0.0
    req = {"messages": [dict(m) for m in msgs]}
    entry = hook.apply(req, {}, cfg)
    assert entry["fire"] == ["reask-note"] and req["mesh_general"] is False
    assert req["messages"][-1]["content"].endswith(hook.REASK_NOTE)
    req = {"messages": [dict(m) for m in msgs], "mesh_fixes": "none"}
    entry = hook.apply(req, {}, cfg)
    assert "fire" not in entry and entry["override"] == ["none"] and "mesh_fixes" not in req
    req = {"messages": [dict(m) for m in msgs]}
    entry = hook.apply(req, {"x-mesh-fixes": "code-followup"}, cfg)
    assert entry["fire"] == ["code-followup"] and req["messages"][-1]["content"] == msgs[-1]["content"]


def test_samples_redact_contact_details(tmp_path):
    cfg = {"flaws": True, "flaws_dir": str(tmp_path), "flaws_samples": True}
    hook.apply({"messages": chat("make a coin", DOOR, "it doesnt work, mail me at kid@example.com")}, {}, cfg)
    assert "example.com" not in (tmp_path / "samples.jsonl").read_text(encoding="utf-8")


def test_route_label_and_safety_substring_keeps_the_general_note():
    m = chat("make a door that opens when i press e", DOOR, "now make it close after 3 seconds")
    assert route.label(m, ["code-followup"]) == "code"
    p = chat("how does photosynthesis work")
    assert route.label(p, ()) == "safety" and route.label(p, ["safety-substring"]) == "general"


def test_grader():
    it = {"grader": {"code": True, "any": [r"task\.wait\(\s*3"], "must_not": items.LEAK}}
    assert items.grade(it, "Here:\n```lua\ntask.wait(3)\n```")[0]
    ok, why = items.grade(it, "This is a general question, not a game-building one.")
    assert not ok and any("no code block" in w for w in why)
    ok, why = items.grade({"grader": {"code": True, "verify": "luau"}}, "```lua\nwait(1)\n```",
                          lambda a: {"ok": False, "blocks": [{"problems": [{"severity": "error", "name": "wait"}]}]})
    assert not ok and "verifier" in why[-1]
    assert not items.grade({"grader": {}}, "```lua\nlocal x = 1\n")[0]          # cut answer


def test_clusters_to_items():
    samples = [{"id": "a1", "can": ["code-followup"], "msgs": chat("make a door", DOOR, "now make it close")},
               {"id": "a2", "can": ["code-followup"], "msgs": chat("make a door", DOOR, "now make it close")}]
    its = items.clusters_to_items(samples)
    assert len(its) == 1 and its[0]["expect"] == "code" and its[0]["grader"]["code"] and its[0]["grader"]["verify"]


def test_miner_clusters_and_next_turn_reask():
    t = time.time()
    rows = [{"ts": t, "model": "litha", "outcome": "failed: no first token within 900 s"},
            {"ts": t, "model": "litha", "outcome": "failed: mesh busy: no usable GPU node (waited 0.0 s)"},
            {"ts": t, "model": "litha", "outcome": "ok", "finish": "length"},
            {"ts": t, "model": "litha", "outcome": "ok", "conv": "c1", "flaw": {"kind": "factual", "sig": ["codectx"],
                                                                               "would": ["code-followup"]}},
            {"ts": t + 30, "model": "litha", "outcome": "ok", "conv": "c1", "flaw": {"kind": "factual",
                                                                                    "sig": ["codectx", "reask"]}},
            {"ts": t, "model": "star-voice", "outcome": "failed: HTTP 500"}]
    lines = ["mesh " + json.dumps(r) for r in rows] + ["noise"]
    res = mine.clusters(mine.parse(lines))
    names = {c["cause"]: c for c in res["clusters"]}
    assert res["requests"] == 5 and names["timeout: no first token within 900 s"]["count"] == 1
    assert "mesh busy: no usable GPU node" in names and "answer cut at max_tokens (finish_reason length)" in names
    assert any(c.startswith("misrouted: follow-up") for c in names)
    assert any("re-asked" in c for c in names) and res["reasked_next"] == 1
    rep = mine.report(res)
    assert rep["kind"] == "eval" and rep["suite"] == "flaws" and "msgs" not in json.dumps(rep)


def test_decide_needs_a_clear_win_and_no_control_loss():
    def r(a, b, cluster=True):
        return {"A": {"pass": a}, "B": {"pass": b}, "cluster": cluster}
    ok, _ = gate.decide("code-followup", [r(False, True)] * 3 + [r(True, True)])
    assert ok
    assert not gate.decide("code-followup", [r(False, True)] * 3 + [r(True, False)] * 2)[0]
    assert not gate.decide("code-followup", [r(False, True)] * 3 + [r(True, False, False)])[0]
    assert not gate.decide("code-followup", [r(False, True)])[0]


def test_ship_and_rollback_watch(tmp_path):
    gate.ship(str(tmp_path), "code-followup", {"ab": {}}, {"reask_rate": 0.1, "fail_rate": 0.0})
    assert "code-followup" in gate.read_shipped(str(tmp_path))["fixes"]
    t = time.time() + 5
    rows = []
    for i in range(25):
        rows.append({"ts": t + i * 100, "model": "litha", "outcome": "ok", "conv": f"c{i}",
                     "flaw": {"kind": "factual", "sig": ["codectx"], "fire": ["code-followup"]}})
        rows.append({"ts": t + i * 100 + 20, "model": "litha", "outcome": "ok", "conv": f"c{i}",
                     "flaw": {"kind": "factual", "sig": ["reask"]}})
    res = gate.watch(str(tmp_path), rows)
    assert res[0]["rollback"] and "code-followup" not in gate.read_shipped(str(tmp_path))["fixes"]


def test_self_model_answers_weak_spot_questions():
    sys.path.insert(0, str(ROOT / "server"))
    from mesh.selfmodel import brief
    sys.path.remove(str(ROOT / "server"))
    for q in ("what are your weak spots?", "what are you bad at", "what do you get wrong", "whats ur biggest flaws"):
        assert brief.wants_self(q) and "flaws" in brief.topic_of(q), q
    assert not brief.wants_self("what are the weak spots of a castle")
    rep = {"kind": "eval", "suite": "flaws", "score": 3, "max": 100, "requests": 100, "ts": time.time(),
           "clusters": [{"cause": "timeout: no first token within 45 s", "group": "capacity", "count": 7, "rate": 0.07}]}
    text = brief.render({"ts": time.time(), "reports": {"flaws": rep, "upgrade": [
        {"component": "flaw-fix:code-followup", "decision": "promote", "why": "won", "ts": time.time()}]}}, "flaws")
    assert "7 x timeout: no first token within 45 s" in text and "Self-fix code-followup" in text


def test_reports_summary_keeps_the_last_flaws_report(tmp_path):
    sys.path.insert(0, str(ROOT / "server"))
    from mesh.selfmodel import reports
    sys.path.remove(str(ROOT / "server"))
    r = reports.Reports(tmp_path)
    assert r.add({"kind": "eval", "suite": "flaws", "score": 1, "clusters": [{"cause": "x", "count": 1}]})[0]
    assert r.add({"kind": "eval", "suite": "mc", "score": 5})[0]
    assert r.summary()["flaws"]["clusters"][0]["cause"] == "x"


def test_long_turns_never_trip_the_rules():
    research = ("QUESTION: On what date was Go 1.27.0 released?\n\nWEB EVIDENCE:\n" +
                "untrusted excerpts: the release adds a new block syntax, account settings, IP address handling. " * 8)
    sig = hook.signals(chat(research))
    assert "long" in sig["flags"] and hook.eligible(sig) == []
    feedback = "The real checks of your answer failed: " + "the server log says error loading the pack. " * 10
    assert hook.eligible(hook.signals(chat("make a data pack", DOOR, feedback))) == []


def test_gate_only_measures_turns_whose_request_changes():
    m = chat("make a door that opens when i press e", DOOR, "where do i put this")
    assert gate.changes(m, "code-followup", set())
    assert not gate.changes(chat("whats the capital of australia"), "code-followup", set())
    assert gate.changes(chat("make a coin", DOOR, "it doesnt work nothing happens"), "reask-note", set())
