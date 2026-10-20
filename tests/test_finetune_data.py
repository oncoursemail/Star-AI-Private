"""Fine-tune pipeline (server/training/finetune): decontamination, slop, private rows, KTO rows, gold weight, gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "training"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bd = _load("ft_build_data", "server/training/finetune/build_data.py")
gr = _load("ft_gate_run", "server/training/finetune/gate_run.py")

GOOD = "```lua\nlocal M = {}\nfunction M.add(a: number, b: number): number\n\treturn a + b + {n}\nend\nreturn M\n```"
EVAL_PROMPT = ("Write a DataStore wrapper module named SafeStore that retries GetAsync with exponential backoff up to "
               "five attempts and logs every failed attempt with the key name")


def _ex(task, prompt, answer, category="economy-x", ts="2026-10-18T00:00:00Z"):
    return {"task": task, "category": category, "prompt": prompt, "answer": answer, "ts": ts,
            "verified": "automated checks", "kind": "first", "lessons": []}


def _fail(task, prompt, answer, ts="2026-10-18T01:00:00Z"):
    return {"task": task, "category": "economy-x", "prompt": prompt, "answer": answer, "ts": ts,
            "reasons": ["unit_tests: 0/3 passed"], "validation": False, "lessons": []}


def _jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def suites(tmp_path):
    root = tmp_path / "evals"
    (root / "reference").mkdir(parents=True)
    tasks = [{"id": "NET-12", "prompt": EVAL_PROMPT}]
    # a template phrase that 3 evaluation prompts share: boilerplate, not a leak
    tasks += [{"id": f"UI-0{i}", "prompt": f"In my Roblox game: write a server script that does thing number {i} "
                                          f"for the {w} panel"} for i, w in enumerate(["shop", "quest", "map"], 1)]
    (root / "golden-tasks-v2.json").write_text(json.dumps(tasks), encoding="utf-8")
    (root / "holdout-v1.json").write_text(json.dumps([{"id": "HO-NET-01", "prompt": "Speed guard for walk speed"}]),
                                          encoding="utf-8")
    (root / "practice-tasks-beginner-v2.json").write_text(json.dumps([{"id": "BEG-01", "prompt": "practice task"}]),
                                                          encoding="utf-8")
    (root / "reference" / "NET-12.md").write_text("```lua\nreturn 1\n```", encoding="utf-8")
    (root / "reference" / "practice-x.md").write_text("practice reference", encoding="utf-8")
    return root


def _build(tmp_path, suites, examples, failures=(), private=(), **kw):
    ex = _jsonl(tmp_path / "s1" / "data" / "examples.jsonl", examples)
    fa = [_jsonl(tmp_path / "s1" / "data" / "failures.jsonl", list(failures))] if failures else []
    pv = [_jsonl(tmp_path / "outbox" / "paintball.jsonl", list(private))] if private else []
    kw.setdefault("ledger_share", 1.0)
    return bd.build([ex], fa, pv, suites, **kw)


def _ids(result, split="train"):
    return {r["task"] for r in result["sft"][split]}


def test_gate_suites_copies_only_golden_and_holdout(tmp_path, suites):
    dest = tmp_path / "copy"
    dest.mkdir()
    bd.gate_suites(suites, dest)
    assert sorted(p.name for p in dest.glob("*.json")) == ["golden-tasks-v2.json", "holdout-v1.json"]
    assert [p.name for p in (dest / "reference").iterdir()] == ["NET-12.md"]


def test_eval_ids_near_copies_and_holdout_are_dropped_but_boilerplate_is_kept(tmp_path, suites):
    rows = [
        _ex("NET-12", "a different text entirely about tweens", GOOD.replace("{n}", "1")),        # eval id
        _ex("practice-datastores-06", EVAL_PROMPT + " and return the value", GOOD.replace("{n}", "2")),  # near copy
        _ex("practice-walk", "Speed guard for walk speed", GOOD.replace("{n}", "3")),             # holdout prompt
        _ex("practice-npc", "In my Roblox game: write a server script that makes an NPC patrol between two "
                            "waypoints with PathfindingService", GOOD.replace("{n}", "4")),        # template only
    ]
    result = _build(tmp_path, suites, rows)
    kept = _ids(result) | _ids(result, "val")
    assert kept == {"practice-npc"}
    reasons = dict(result["contaminated"])
    assert reasons["NET-12"] == "task id is an evaluation id"
    assert "practice-datastores-06" in reasons and "practice-walk" in reasons


def test_embedding_rule_drops_semantic_neighbours(tmp_path, suites):
    def embed(texts):    # a fake embedder: texts mentioning "backoff" point the same way as the eval prompt
        return [[1.0, 0.0] if "backoff" in t.lower() else [0.0, -1.0] if "spin" in t else [0.0, 1.0] for t in texts]
    rows = [_ex("practice-retry", "Make GetAsync calls robust: retry with backoff", GOOD.replace("{n}", "1")),
            _ex("practice-other", "Make a part spin forever", GOOD.replace("{n}", "2"))]
    result = _build(tmp_path, suites, rows, embed=embed, cosine=0.75)
    assert _ids(result) | _ids(result, "val") == {"practice-other"}
    assert dict(result["contaminated"])["practice-retry"] == "prompt embedding is close to an evaluation prompt"


def test_slop_answers_are_dropped_and_footer_cut(tmp_path, suites):
    slop = "```lua\nlocal M = {}\nfunction M.run()\n\t-- TODO: implement this\nend\nreturn M\n```"
    clean = GOOD.replace("{n}", "1") + "\n\n---\n**Sources retrieved by STAR**\n1. https://create.roblox.com/docs"
    result = _build(tmp_path, suites, [_ex("practice-a", "make a counter module", slop),
                                       _ex("practice-b", "make an adder module", clean)])
    assert result["counts"]["slop_dropped"] == 1
    rows = result["sft"]["train"] + result["sft"]["val"]
    assert [r["task"] for r in rows] == ["practice-b"]
    assert "Sources retrieved by STAR" not in rows[0]["body"]


def test_private_rows_train_locally_but_never_in_public_output(tmp_path, suites):
    private = [{"id": "night-school-paintball-x", "group_id": "paintball-x", "task_category": "rounds-teams",
                "instruction": "Paintball rule: who wins a round", "response": GOOD.replace("{n}", "9")}]
    rows = [_ex("river-case-1", "river native case", GOOD.replace("{n}", "1"), category="river-paintball-native"),
            _ex("practice-a", "make an adder module", GOOD.replace("{n}", "2"))]
    local = _build(tmp_path, suites, rows, private=private)
    public = _build(tmp_path, suites, rows, private=private, public=True)
    everything = lambda r: {x["task"] for x in r["sft"]["train"] + r["sft"]["val"]}   # noqa: E731
    assert {"paintball-x", "river-case-1"} <= everything(local)
    assert everything(public) == {"practice-a"}
    assert all(not x["private"] for split in ("train", "val") for x in public["kto"][split])


def test_kto_rows_use_failures_of_solved_tasks_only_capped_per_task(tmp_path, suites):
    rows = [_ex("practice-a", "make an adder module", GOOD.replace("{n}", "1"))]
    failures = [_fail("practice-a", "make an adder module", f"```lua\nreturn {i}\n```", ts=f"2026-10-18T0{i}:00:00Z")
                for i in range(5)]
    failures.append(_fail("practice-unsolved", "an unsolved task", "```lua\nreturn nil\n```"))
    result = _build(tmp_path, suites, rows, failures=failures, max_fail_per_task=3)
    kto = result["kto"]["train"] + result["kto"]["val"]
    assert sorted(r["label"] for r in kto) == [False, False, False, True]
    assert {r["id"] for r in kto} == {"practice-a"}
    newest = [r["completion"][0]["content"] for r in kto if not r["label"]]
    assert newest == ["```lua\nreturn 4\n```", "```lua\nreturn 3\n```", "```lua\nreturn 2\n```"]
    assert result["counts"]["failure_rows_dropped_over_cap"] == 2


def test_ledger_family_is_capped(tmp_path, suites):
    rows = [_ex(f"LG-X-{i:02d}", f"ledger task number {i} for module {i}", GOOD.replace("{n}", str(i)),
                category="ledger-real-builtins") for i in range(30)]
    rows += [_ex(f"practice-{i}", f"hand written task {i} about a door {i}", GOOD.replace("{n}", str(100 + i)))
             for i in range(10)]
    result = _build(tmp_path, suites, rows, ledger_share=0.5)
    train = result["sft"]["train"]
    hand = sum(1 for r in train if r["family"] != "ledger")
    assert sum(1 for r in train if r["family"] == "ledger") <= hand
    assert result["counts"]["ledger_capped"] > 0


def test_gold_rows_weigh_more_and_lead_the_bank(tmp_path, suites):
    gold = _jsonl(tmp_path / "gold.jsonl", [{"group_id": f"g{i}", "task_category": "docs", "instruction":
                                             f"gold task {i} about a lamp {i}", "response": GOOD.replace("{n}", str(50 + i))}
                                            for i in range(20)])
    rows = [_ex(f"practice-{i}", f"self task {i} about a door {i}", GOOD.replace("{n}", str(i))) for i in range(20)]
    result = _build(tmp_path, suites, rows, gold_files=[gold], gold_weight=2)
    train = result["sft"]["train"]
    gold_train = [r for r in train if r["origin"] == "gold"]
    assert gold_train and len(gold_train) == 2 * len({r["task"] for r in gold_train})
    n_gold = len({r["task"] for r in gold_train})
    assert all(b["group_id"].startswith("gold:") for b in result["bank"][:n_gold])
    assert len(result["bank"]) == len({r["task"] for r in train})


def test_bank_rows_import_into_the_apps_worked_examples(tmp_path, suites):
    from star import worked_examples
    rows = [_ex("practice-a", "make an adder counter widget", GOOD.replace("{n}", "1")),
            _ex("practice-b", "spawn a lava brick obstacle", GOOD.replace("{n}", "2"))]
    result = _build(tmp_path, suites, rows)
    bank = _jsonl(tmp_path / "bank.jsonl", result["bank"])
    worked_examples.import_file(bank, home=tmp_path / "home", project="eval-x")
    block, used = worked_examples.select(tmp_path / "home", "eval-x", "an adder counter widget please", max_chars=2400)
    assert [e.group_id for e in used] == ["practice-a"]


def test_gate_run_wraps_run_task_with_knowledge_and_bank(tmp_path, monkeypatch):
    from star import desktop_core, worked_examples
    seen = {}

    def fake_run_task(settings, prompt, **kwargs):
        seen.update(knowledge=settings.knowledge_endpoint, examples=settings.worked_examples_enabled,
                    imported=(desktop_core.app_data() / "worked_examples.sqlite3").is_file())
        return "answer"

    monkeypatch.setattr(desktop_core, "run_task", fake_run_task)
    monkeypatch.setattr(worked_examples, "MAX_PROMPT_CHARS", worked_examples.MAX_PROMPT_CHARS)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    bank = _jsonl(tmp_path / "bank.jsonl", [bd.bank_row({"task": "t1", "category": "c", "prompt": "make a door",
                                                          "body": GOOD.replace("{n}", "1")})])
    gr.patch_run_task("http://knowledge.test:8091", bank, 8000)
    assert desktop_core.run_task(desktop_core.Settings(project="eval-net-12"), "task") == "answer"
    assert seen == {"knowledge": "http://knowledge.test:8091", "examples": True, "imported": True}
    assert worked_examples.MAX_PROMPT_CHARS == 8000


def test_kto_loss_direction():
    torch = pytest.importorskip("torch")
    sys.path.insert(0, str(ROOT / "server" / "training" / "apprentice"))
    pytest.importorskip("psutil")
    kto = _load("ft_train_kto", "server/training/finetune/train_kto.py")
    lo, hi = torch.tensor(-1.0), torch.tensor(1.0)
    assert kto.kto_loss(hi, True, 0.0, 0.5) < kto.kto_loss(lo, True, 0.0, 0.5)
    assert kto.kto_loss(hi, False, 0.0, 0.5) > kto.kto_loss(lo, False, 0.0, 0.5)
