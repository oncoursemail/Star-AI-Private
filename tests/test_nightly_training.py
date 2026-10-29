"""Nightly self-training (server/training/nightly): promotion gate, decontamination, verdict parsing, GPU hold."""
from __future__ import annotations

import datetime as dt
import importlib
import json
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

D = importlib.import_module("training.nightly.data")
H = importlib.import_module("training.nightly.gpu_hold")
S = importlib.import_module("training.nightly.score")
N = importlib.import_module("training.nightly.nightly")


def rows(passes, problems=0):
    return [{"id": str(i), "pass": p, "verify_problems": problems} for i, p in enumerate(passes)]


def test_decide_promotes_only_a_clear_safe_gain():
    base = rows([False] * 10 + [True] * 10)
    better = rows([True] * 6 + [False] * 4 + [True] * 10)
    safe = rows([True] * 5)
    d = N.decide(base, better, safe, safe, margin=3)
    assert d["promote"] and d["wins"] == 6 and d["losses"] == 0
    assert not N.decide(base, rows([True] * 2 + [False] * 8 + [True] * 10), safe, safe, 3)["promote"]  # +2 < 3


def test_decide_blocks_safety_and_verifier_regressions():
    base = rows([False] * 10 + [True] * 10)
    better = rows([True] * 6 + [False] * 4 + [True] * 10)
    d = N.decide(base, better, rows([True] * 5), rows([True] * 4 + [False]), 3)
    assert not d["promote"] and any("safety" in r for r in d["reasons"])
    d = N.decide(rows([False] * 10 + [True] * 10, 0), rows([True] * 6 + [False] * 4 + [True] * 10, 1),
                 rows([True]), rows([True]), 3)
    assert not d["promote"] and any("verifier" in r for r in d["reasons"])


def test_decide_needs_more_wins_than_losses():
    base = rows([True] * 5 + [False] * 15)
    new = rows([False] * 5 + [True] * 10 + [False] * 5)      # +5 net but 5 losses vs 10 wins: ok
    assert N.decide(base, new, [], [], 3)["promote"]
    new2 = rows([False] * 5 + [True] * 8 + [False] * 7)       # +3, wins 8 losses 5
    assert N.decide(base, new2, [], [], 3)["promote"]
    assert N.sign_test_p(0, 0) == 1.0 and N.sign_test_p(10, 0) < 0.01


def test_similar_catches_paraphrases_not_topics():
    assert D.similar("how do i make a door open when i press e in roblox", "make a door open with e in roblox")
    assert not D.similar("how do I save coins with DataStore", "how do I make a door open with E")


def test_heldout_items_and_close_prompts_are_never_in_the_pool(tmp_path):
    distill = {"items": [
        {"id": "rb-door-e", "question": "How do I make a door that opens when I press E?",
         "paraphrases": [], "held_out": ["press E to open a door"], "generated_paraphrases": ["door open with e key"]},
        {"id": "rb-coins", "question": "How do I give players coins every minute?",
         "paraphrases": [], "held_out": [], "generated_paraphrases": ["coins every minute roblox script",
                                                                       "give coins each 60 seconds"]},
        {"id": "rb-tween", "question": "How do I tween a part?", "paraphrases": [], "held_out": [],
         "generated_paraphrases": ["tween part smoothly", "how to tween a part"]}]}
    qset = {"items": [{"id": "d:rb-door-e", "prompt": "How do I make a door that opens when I press E?"},
                      {"id": "e:x", "prompt": "How do I tween a part smoothly in Roblox?"}]}
    evalq = {"questions": [{"id": "e1", "prompt": "Why does my leaderstats script not show coins?"}]}
    queries = [{"ok": True, "text_sha": "a" * 64, "question": "What does TweenService:Create return?",
                "task": "Write a door that opens when the player presses E near it.", "path": "p"}]
    paths = {}
    for name, obj in (("d.json", distill), ("q.json", qset), ("e.json", evalq)):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
        paths[name] = str(tmp_path / name)
    (tmp_path / "qs.jsonl").write_text("\n".join(json.dumps(r) for r in queries), encoding="utf-8")
    res = D.build_pool(paths["d.json"], str(tmp_path / "qs.jsonl"), "", paths["q.json"], paths["e.json"])
    prompts = {p["prompt"] for p in res["pool"]}
    assert "rb-door-e" in res["banned_items"] and "rb-tween" in res["banned_items"]   # in eval / close to eval
    assert "door open with e key" not in prompts and "how to tween a part" not in prompts
    assert "coins every minute roblox script" in prompts
    assert all(p["source"] for p in res["pool"])
    assert "How do I give players coins every minute?" not in prompts          # agent-written text never used


def test_night_sample_skips_used_and_caps_per_item():
    pool = [{"pid": f"d{i}", "group": "d:same", "prompt": str(i)} for i in range(5)] + \
           [{"pid": f"q{i}", "group": f"q:{i}", "prompt": "q" + str(i)} for i in range(10)]
    s = D.night_sample(pool, 6, used={"q0"}, seed=1)
    assert len(s) == 6 and sum(p["group"] == "d:same" for p in s) == 2 and all(p["pid"] != "q0" for p in s)


@pytest.mark.parametrize("text,ok", [('{"verdict": "pass", "reason": "fine"}', True),
                                     ('Sure. {"verdict":"FAIL","reason":"LocalScript in Workspace"}', False),
                                     ("PASS", True), ("no idea", None)])
def test_parse_verdict(text, ok):
    assert S.parse_verdict(text)[0] is ok


def test_full_check_fails_cut_off_answers_without_calling_tools():
    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("judge must not run")
    r = S.full_check(Boom(), None, "q", {"text": "partial", "finish": "length"})
    assert r == {"finished": False, "pass": False}


def test_window_and_until():
    assert H.in_window(dt.datetime(2026, 10, 29, 0, 30))
    assert not H.in_window(dt.datetime(2026, 10, 29, 7, 50))
    assert not H.in_window(dt.datetime(2026, 10, 28, 22, 0))
    assert abs(H.minutes_until("07:45", dt.datetime(2026, 10, 29, 0, 30)) - 435) < 1e-6


def test_turbo_pause_only_removes_our_own_off_file(tmp_path, monkeypatch):
    off = tmp_path / "OFF"
    monkeypatch.setattr(H, "TURBO_OFF", off)
    H.pause_turbo()
    assert off.read_text(encoding="utf-8").strip() == H.TURBO_MARK
    H.resume_turbo()
    assert not off.exists()
    off.write_text("owner turned it off\n", encoding="utf-8")
    H.pause_turbo()
    H.resume_turbo()
    assert off.exists()


def test_owner_active_ignores_soft_busy(monkeypatch):
    monkeypatch.setattr(H, "idle_seconds", lambda: 9999)
    monkeypatch.setattr(H, "node", lambda *a, **k: (200, {"state": "busy", "reason": "only 118 MB of graphics "
                                                           "memory is free (6175 MB needed)"}))
    assert H.owner_active(120) == ""
    monkeypatch.setattr(H, "node", lambda *a, **k: (200, {"state": "busy", "reason": "RobloxPlayerBeta.exe is running"}))
    assert "Roblox" in H.owner_active(120)
    monkeypatch.setattr(H, "idle_seconds", lambda: 5)
    assert "owner input" in H.owner_active(120)


def test_chunked_loss_matches_full_cross_entropy():
    torch = pytest.importorskip("torch")
    from training.nightly.fit_probe import chunked_loss
    torch.manual_seed(0)
    h = torch.randn(10, 8, requires_grad=True)
    head = torch.randn(20, 8)
    y = torch.randint(0, 20, (10,))
    ref = torch.nn.functional.cross_entropy(30 * torch.tanh((h @ head.t()) / 30), y)
    got = chunked_loss(h, y, head, 30.0, chunk=3)
    assert torch.allclose(ref, got, atol=1e-5)


def test_open_hold_of_another_lane_blocks(tmp_path, monkeypatch):
    sched = tmp_path / "gpu-lab-schedule.md"
    now = dt.datetime.now(dt.timezone.utc)
    t = (now - dt.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%MZ")
    old = (now - dt.timedelta(hours=9)).strftime("%Y-%m-%dT%H:%MZ")
    sched.write_text(f"HOLD stale {old} x\nHOLD gpu-pool {t} planned\nHOLD nightly-training {t} mine\n"
                     f"PLANNED other HOLD {t}\n", encoding="utf-8")
    monkeypatch.setenv("STAR_GPU_SCHEDULE", str(sched))
    assert "gpu-pool" in H.open_hold("nightly-training")
    sched.write_text(sched.read_text(encoding="utf-8") + f"FREE gpu-pool {t} done\n", encoding="utf-8")
    assert H.open_hold("nightly-training") == ""


def test_open_hold_ignores_holds_on_star_pc_card(tmp_path, monkeypatch):
    sched = tmp_path / "gpu-lab-schedule.md"
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    sched.write_text(f"HOLD gpu-pool {t} star-pc 4060 only, planned end +20 min\n", encoding="utf-8")
    monkeypatch.setenv("STAR_GPU_SCHEDULE", str(sched))
    assert H.open_hold("nightly-training") == ""


# ---- nightly v2: corrections, gap prompts, shards, ORPO, fitted schedule, node wiring -----------------------------
C = importlib.import_module("training.nightly.correct")
T = importlib.import_module("training.nightly.train")
DP = importlib.import_module("training.nightly.deploy")


def test_feedback_lines_use_only_our_checks():
    chk = {"verify": {"ok": False, "details": [{"kind": "mc_function", "name": None, "answer_line": 4,
                                                "message": "commands in a .mcfunction file have no leading '/'",
                                                "suggestion": "give"}]},
           "rule_hits": [{"rule": "touched-no-debounce", "message": "Add a debounce.", "evidence": "Touched:Connect"}],
           "judge": {"pass": False, "reason": "No cooldown on the remote."}}
    lines = C.feedback_lines(chk)
    assert lines[0].startswith("commands in a .mcfunction") and "(use: give)" in lines[0] and "[line 4]" in lines[0]
    assert "Add a debounce. (seen here: Touched:Connect)" in lines
    assert lines[-1] == "A reviewer said: No cooldown on the remote."
    assert C.feedback_lines({"finished": False}, finish="length")[0].startswith("The answer was too long")
    assert C.feedback_lines({"verify": {"ok": True}, "judge": {"pass": True}}) == []


@pytest.mark.parametrize("text,out", [("Here's the fixed version:\n\nUse task.wait()", "Use task.wait()"),
                                      ("Sure! Here is the answer\nUse task.wait()", "Use task.wait()"),
                                      ("I fixed the problems listed by the checker: ...", None),
                                      ("Use task.wait() instead of wait().", "Use task.wait() instead of wait().")])
def test_clean_rewrite(text, out):
    assert C.clean(text) == out


class FakeSrv:
    parallel = 1

    def __init__(self, fact='{"false_claims": [], "answers_question": true}'):
        self.calls = []
        self.fact = fact

    def chat(self, messages, temperature=0.3, max_tokens=1200, seed=-1, **kw):
        self.calls.append(messages)
        if messages[0]["content"] == S.FACT_SYSTEM:
            return {"text": self.fact, "finish": "stop", "tokens": 5}
        last = messages[-1]["content"]
        text = "GOOD rewrite" if last.startswith(C.ASK) else ("GOOD first" if "easy" in last else "bad first")
        return {"text": text, "finish": "stop", "tokens": 10, "tok_s": 50.0, "draft_n": 8, "draft_ok": 6}


def test_harvest_banks_first_try_and_corrected_answers(tmp_path, monkeypatch):
    def fake_check(srv, verifier, q, ans, safety=False, reference=""):
        ok = ans["text"].startswith("GOOD")
        return {"finished": True, "verify": {"ok": ok}, "rules": [], "rule_hits": [],
                "judge": {"pass": ok, "reason": "" if ok else "Uses a deprecated API."}, "pass": ok}
    monkeypatch.setattr(N.S, "full_check", fake_check)
    sysf = tmp_path / "sys.txt"
    sysf.write_text("You are Litha.", encoding="utf-8")
    cfg = {"system_prompt": str(sysf), "work_dir": str(tmp_path)}
    prompts = [{"pid": "a1", "prompt": "an easy one", "group": "q:1", "source": "s"},
               {"pid": "b2", "prompt": "a hard one", "group": "g:mc-commands", "source": "s"}]
    srv = FakeSrv()
    st = N.harvest(cfg, srv, None, prompts, 2, tmp_path, lambda m: None, should_stop=lambda: False)
    bank = N.jl_read(tmp_path / "bank.jsonl")
    assert {(r["id"], r["kind"]) for r in bank} == {("a1", "first"), ("b2", "corrected")}
    assert next(r for r in bank if r["id"] == "b2")["messages"][-1]["content"] == "GOOD rewrite"
    pairs = N.jl_read(tmp_path / "pairs.jsonl")
    assert [(p["id"], p["chosen"], p["rejected"]) for p in pairs] == [("b2", "GOOD rewrite", "bad first")]
    assert st["corrections_tried"] == 1 and st["corrections_pass"] == 1 and st["draft_accept"] == 0.75
    fix_call = [c for c in srv.calls if c[-1]["content"].startswith(C.ASK)][0]
    assert "A reviewer said: Uses a deprecated API." in fix_call[-1]["content"]
    assert {r["pid"] for r in N.jl_read(tmp_path / "harvest_index.jsonl")} == {"a1", "b2"}


def test_training_rows_dedupe_and_upsample_corrected():
    bank = [{"id": "a", "kind": "first"}, {"id": "b", "kind": "corrected"}, {"id": "a", "kind": "corrected"}]
    rows = N.training_rows(bank, 2)
    assert [r["id"] for r in rows] == ["a", "b", "b"]
    tr, va = N.split_rows([{"id": str(i), "kind": "first"} for i in range(200)] + [{"id": "0", "kind": "x"}], 1)
    assert not {r["id"] for r in tr} & {r["id"] for r in va} and len(va) == 10


def test_night_sample_gap_share_and_disjoint_shards():
    pool = [{"pid": f"g{c}{i}", "group": f"g:{c}", "prompt": f"{c}{i}"} for c in "xy" for i in range(20)] + \
           [{"pid": f"q{i}", "group": f"q:{i}", "prompt": f"q{i}"} for i in range(40)]
    s = D.night_sample(pool, 10, set(), seed=3, gap_share=0.4)
    groups = [p["group"] for p in s]
    assert len(s) == 10 and groups.count("g:x") == 2 and groups.count("g:y") == 2
    a = D.night_sample(pool, 30, set(), 3, shard=(0, 2), gap_share=0.3)
    b = D.night_sample(pool, 30, set(), 3, shard=(1, 2), gap_share=0.3)
    assert a and b and not {p["pid"] for p in a} & {p["pid"] for p in b}
    assert D.parse_shard("1/2") == (1, 2)


def test_orpo_coefficients_match_numeric_gradient():
    lc, lr, beta, h = -0.4, -1.3, 0.1, 1e-6
    dc, dr, loss = T.orpo_coefficients(lc, lr, beta)
    assert abs(dc - (T.orpo_coefficients(lc + h, lr, beta)[2] - T.orpo_coefficients(lc - h, lr, beta)[2]) / (2 * h)) < 1e-4
    assert abs(dr - (T.orpo_coefficients(lc, lr + h, beta)[2] - T.orpo_coefficients(lc, lr - h, beta)[2]) / (2 * h)) < 1e-4
    assert dc < -1 and dr > 0            # push the chosen answer up, the rejected one down
    assert T.orpo_coefficients(-0.1, -9.0, 0.1)[2] < T.orpo_coefficients(-0.1, -0.11, 0.1)[2]


def test_fit_steps_shrinks_to_the_time_box():
    assert T.fit_steps(100, 10, 600, 3000) == 50          # 60 s/step, 2400 s left -> 40 more
    assert T.fit_steps(100, 10, 60, 30000) == 100
    assert T.fit_steps(100, 10, 600, 300) == 11


def test_deploy_config_roundtrip():
    cfg = {"llama_args": ["-ngl", "99", "--lora", "old.gguf", "-t", "4"], "ngl_ladder": [[100, 7300, "mtp"], [99, 7130]]}
    new = DP.with_adapter(cfg, "C:/x/litha-nightly.gguf", 1.0, mb=140)
    assert new["llama_args"] == ["-ngl", "99", "-t", "4", "--lora-scaled", "C:/x/litha-nightly.gguf", "1.0"]
    assert [s[1] for s in new["ngl_ladder"]] == [7440, 7270]
    again = DP.with_adapter(new, "C:/x/next.gguf", 1.0, mb=100)
    assert [s[1] for s in again["ngl_ladder"]] == [7400, 7230] and again["llama_args"].count("--lora-scaled") == 1
    back = DP.without_adapter(again)
    assert back["llama_args"] == ["-ngl", "99", "-t", "4"] and [s[1] for s in back["ngl_ladder"]] == [7300, 7130]
    assert "nightly_lora" not in back


def test_fact_check_blocks_a_corrected_answer_with_a_false_claim(tmp_path, monkeypatch):
    def fake_check(srv, verifier, q, ans, safety=False, reference=""):
        ok = ans["text"].startswith("GOOD")
        return {"finished": True, "verify": {"ok": ok}, "rules": [], "rule_hits": [],
                "judge": {"pass": ok, "reason": "" if ok else "Wrong."}, "pass": ok}
    monkeypatch.setattr(N.S, "full_check", fake_check)
    sysf = tmp_path / "sys.txt"
    sysf.write_text("You are Litha.", encoding="utf-8")
    srv = FakeSrv(fact='{"false_claims": ["Minecraft has no loot tables"], "answers_question": true}')
    st = N.harvest({"system_prompt": str(sysf), "work_dir": str(tmp_path)}, srv, None,
                   [{"pid": "b2", "prompt": "a hard one", "group": "g:mc-datapack", "source": "s"}], 2, tmp_path,
                   lambda m: None, should_stop=lambda: False)
    assert st["corrections_pass"] == 0 and N.jl_read(tmp_path / "bank.jsonl") == []
    second = [c for c in srv.calls if c[-1]["content"].startswith(C.ASK)][-1][-1]["content"]
    assert "A fact checker says this is false: Minecraft has no loot tables" in second
