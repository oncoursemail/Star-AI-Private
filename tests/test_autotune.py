"""Star tunes herself (server/mesh/autotune/autotune.py): bounded candidates, the keep/reject rule, and whole nightly
runs against a fake engine and a fake node (keep, reject on quality loss, automatic rollback, gates)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "mesh" / "autotune"))
import autotune as at  # noqa: E402
sys.path.remove(str(ROOT / "server" / "mesh" / "autotune"))

NODE = json.loads((ROOT / "server" / "mesh" / "node" / "node.json").read_text(encoding="utf-8"))
RIGHT = ["391", "Canberra", "tenalp", "8", "local function add(a, b)\n  return a + b\nend", "Players", "3000", "32",
         "Mars", "No, 91 = 7 x 13."]


def test_candidates_are_single_knob_bounded_and_rotate():
    cfg = dict(NODE)
    cands = at.candidates(cfg, 0, cores=6, night=0, limit=10)
    names = [c["name"] for c in cands]
    assert names == ["threads 4->2", "threads 4->6", "ubatch 128->64", "ubatch 128->256", "draft_n 4->3", "draft_n 4->5",
                     "kv_type q4_0->q8_0"]
    for c in cands:   # exactly one knob changed, the rest identical
        diff = [k for k in ("llama_args", "step_args") if c["config"].get(k) != cfg.get(k)]
        assert len(diff) == 1
    assert at.get_arg(cands[3]["config"]["llama_args"], "-ub") == "256"
    assert at.get_arg(cands[5]["config"]["step_args"]["mtp"], "--spec-draft-n-max") == "5"
    assert cfg["llama_args"] == NODE["llama_args"]                                  # input untouched
    # a plain (no drafter) step has no draft knob; rotation + limit
    plain = [c["name"] for c in at.candidates(cfg, 2, cores=6, night=0, limit=10)]
    assert not any(n.startswith("draft_n") for n in plain)
    assert [c["name"] for c in at.candidates(cfg, 0, cores=6, night=2, limit=3)] == names[2:5]
    assert at.candidates({"llama_args": []}, None) == []


def test_quality_scoring():
    assert at.quality(RIGHT) == 10
    wrong = list(RIGHT)
    wrong[0], wrong[9] = "390", "Yes, it is prime."
    assert at.quality(wrong) == 8


def test_decide_needs_a_real_gain_and_no_quality_loss():
    base = [{"tok_s": 40.0, "quality": 10}, {"tok_s": 42.0, "quality": 10}]
    tried = [{"name": "a", "tok_s": 41.5, "quality": 10}, {"name": "b", "tok_s": 50.0, "quality": 9},
             {"name": "c", "tok_s": 44.0, "quality": 10, "free_at_peak_mb": 50}, {"name": "d", "tok_s": None, "quality": 0},
             {"name": "e", "tok_s": 43.0, "quality": 10}]
    v = at.decide(base, tried, 0.03, 100)
    assert v["decision"] == "keep" and v["winner"]["name"] == "e" and v["baseline_tok_s"] == 41.0
    assert [t["verdict"].split()[0] for t in tried] == ["41.5", "quality", "only", "did", "better"]
    assert at.decide(base, tried[:2], 0.03, 100)["decision"] == "reject"
    assert at.decide([{"tok_s": None, "quality": 0}], tried, 0.03, 100)["decision"] == "abort"


class FakeEngine:
    def __init__(self, speeds=None, bad_quality=(), foreign=0):
        self.speeds, self.bad, self.foreign, self.cfg, self.started = speeds or {}, bad_quality, foreign, None, []

    def gpu(self):
        return {"free": 7500, "total": 8192, "used": 692}

    def foreign_mb(self):
        return self.foreign

    def start(self, cfg, step):
        self.cfg = cfg
        self.started.append((at.get_arg(cfg["llama_args"], "-ub"), at.get_arg(cfg["llama_args"], "-t"), step))

    def chat(self, prompt, max_tokens):
        ub = at.get_arg(self.cfg["llama_args"], "-ub")
        kv = at.get_arg(self.cfg["llama_args"], "-ctk")
        tps = self.speeds.get(ub, 45.0)
        for i, (q, _) in enumerate(at.EVAL):
            if q == prompt:
                return ("wrong" if (kv, i) in self.bad else RIGHT[i]), tps
        return "words " * 20, tps

    def stop(self):
        self.cfg = None


class FakeNode:
    def __init__(self, home, after_restart=("idle", True, 46.0)):
        self.home, self.after, self.restarted = home, after_restart, 0

    def status(self, cfg, home):
        if (self.home / "OFF").exists():
            return {"state": "off", "reason": "the OFF file exists", "models": [{"loaded": False}]}
        if self.restarted:
            state, loaded, tok = self.after
            return {"state": state, "models": [{"loaded": loaded, "tok_s": tok, "in_flight": 0}]}
        return {"state": "idle", "models": [{"loaded": True, "tok_s": 45.0, "in_flight": 0}]}

    def restart(self, home):
        self.restarted += 1


@pytest.fixture()
def home(tmp_path):
    shutil.copy(ROOT / "server" / "mesh" / "node" / "node_agent.py", tmp_path / "node_agent.py")
    cfg = {**NODE, "node": "test-pc", "resume_seconds": 0, "autotune": {"load_timeout_s": 0.05, "max_candidates": 7}}
    (tmp_path / "node.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (tmp_path / "logs").mkdir()
    return tmp_path


def _run(home, engine, node, **kw):
    return at.run(home, now=True, engine=engine, status=node.status, restart=node.restart, sleep=lambda s: None, **kw)


def test_run_keeps_a_measured_win_and_restarts_the_node(home):
    node = FakeNode(home)
    rec = _run(home, FakeEngine(speeds={"256": 49.0}), node)
    assert rec["decision"] == "keep" and rec["candidate"] == "ubatch 128->256" and rec["tok_s"] == 49.0
    cfg = json.loads((home / "node.json").read_text())
    assert at.get_arg(cfg["llama_args"], "-ub") == "256" and cfg["node"] == "test-pc"     # other keys kept
    assert (home / "autotune" / rec["backup"]).is_file() and node.restarted == 1
    assert not (home / "OFF").exists() and not (home / "AUTOTUNE_RUNNING").exists()
    logged = [json.loads(x) for x in (home / "logs" / "autotune.jsonl").read_text().splitlines()]
    assert logged[-1]["decision"] == "keep" and rec["report"] == "no router/token"


def test_run_rejects_a_faster_candidate_that_loses_quality(home):
    before = (home / "node.json").read_text()

    class Faster(FakeEngine):   # KV q8_0 is much faster here but answers one mini-eval question wrong
        def chat(self, prompt, max_tokens):
            text, tps = FakeEngine.chat(self, prompt, max_tokens)
            return text, (60.0 if at.get_arg(self.cfg["llama_args"], "-ctk") == "q8_0" else 45.0)
    f = Faster(bad_quality={("q8_0", 3)})
    rec = _run(home, f, FakeNode(home))
    assert rec["decision"] == "reject" and (home / "node.json").read_text() == before
    kv = next(t for t in rec["tried"] if t["name"] == "kv_type q4_0->q8_0")
    assert kv["tok_s"] == 60.0 and kv["verdict"].startswith("quality 9 < 10")
    assert not (home / "OFF").exists()


def test_run_rolls_back_when_the_node_does_not_come_back(home):
    before = (home / "node.json").read_text()
    node = FakeNode(home, after_restart=("away", False, None))
    rec = _run(home, FakeEngine(speeds={"256": 49.0}), node)
    assert rec["decision"] == "rollback" and (home / "node.json").read_text() == before and node.restarted == 2


def test_dry_run_changes_nothing(home):
    before = (home / "node.json").read_text()
    rec = _run(home, FakeEngine(speeds={"256": 49.0}), FakeNode(home), dry_run=True)
    assert rec["decision"] == "would-keep" and (home / "node.json").read_text() == before


def test_gates(home):
    (home / "OFF").write_text("bench lane")
    assert _run(home, FakeEngine(), FakeNode(home))["decision"] == "skip"
    assert (home / "OFF").read_text() == "bench lane"                     # someone else's park is left alone
    (home / "OFF").unlink()

    class Busy(FakeNode):
        def status(self, cfg, home):
            return {"state": "busy", "reason": "RobloxPlayerBeta.exe", "models": [{"loaded": False}]}
    rec = _run(home, FakeEngine(), Busy(home))
    assert rec["decision"] == "skip" and "RobloxPlayerBeta" in rec["why"]
    rec = at.run(home, engine=FakeEngine(), status=FakeNode(home).status, restart=lambda h: None,
                 sleep=lambda s: None) if not 1 <= at._now_hour() < 6 else {"decision": "skip"}
    assert rec["decision"] == "skip"


def test_owner_starts_a_game_mid_run(home):
    before = (home / "node.json").read_text()
    rec = _run(home, FakeEngine(foreign=2500), FakeNode(home))
    assert rec["decision"] == "abort" and "another program" in rec["why"]
    assert (home / "node.json").read_text() == before and not (home / "OFF").exists()


def test_gpu_lab_schedule_hold_blocks_and_notes_are_written(home):
    import time as _t
    sched = home / "gpu-lab-schedule.md"
    now = _t.strftime("%Y-%m-%dT%H:%MZ", _t.gmtime())
    sched.write_text(f"# schedule\nHOLD nightly-training {now} planned end +19 min (QLoRA)\n", encoding="utf-8")
    cfg = json.loads((home / "node.json").read_text())
    cfg["autotune"]["schedule_file"] = str(sched)
    (home / "node.json").write_text(json.dumps(cfg))
    rec = _run(home, FakeEngine(), FakeNode(home))
    assert rec["decision"] == "skip" and "nightly-training" in rec["why"]
    sched.write_text(sched.read_text() + f"FREE nightly-training {now} (done)\n", encoding="utf-8")
    rec = _run(home, FakeEngine(speeds={"256": 49.0}), FakeNode(home))
    assert rec["decision"] == "keep"
    lines = sched.read_text().splitlines()
    assert lines[-2].startswith("HOLD autotune ") and lines[-1].startswith("FREE autotune ")
    assert at.open_hold(sched) is None
