"""Gold exemplar bank: authoring format, verifier pieces that run offline, the shipped bank, and retrieval."""
import asyncio
import json
from pathlib import Path

import pytest

from star import gold_bank, gold_bank_verify as gv

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ITEM = ROOT / "data" / "gold_bank" / "src" / "security" / "gb-sec-token-bucket-limiter.md"

ITEM = """---
id: gb-test-sample
category: remote-security
topics: remotes, validation
source: original
---
# Request
Validate a number a client sends.

# Answer
Check the type and range on the server.

```lua
--!strict
local M = {}
function M.ok(value: unknown): boolean
	return type(value) == "number" and value == value and value >= 0 and value <= 10
end
return M
```

- NaN fails `value == value`.

# Test
```lua
check("in range", item.ok(5))
check("nan", not item.ok(0 / 0))
```
"""


def row(ident, category, request, answer="```lua\nreturn 1\n```", kind="original", **extra):
    source = {"kind": kind, "spdx": "LicenseRef-STAR-Original" if kind == "original" else "MIT", "url": ""}
    source.update(extra)
    return {"id": ident, "category": category, "topics": ["t"], "request": request, "answer": answer,
            "source": source, "checks": {}, "verified": True}


def write_bank(tmp_path, rows):
    path = tmp_path / "bank.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# --- authoring format ----------------------------------------------------------------------------------------------

def test_parse_item_reads_front_matter_sections_and_blocks():
    item = gv.parse_item(ITEM)
    assert (item.id, item.category, item.source) == ("gb-test-sample", "remote-security", "original")
    assert item.topics == ["remotes", "validation"]
    assert item.request == "Validate a number a client sends."
    assert len(item.blocks) == 1 and item.blocks[0].startswith("--!strict")
    assert item.test.startswith('check("in range"') and item.setup == ""
    assert gv.parse_item(REFERENCE_ITEM.read_text(encoding="utf-8"), str(REFERENCE_ITEM)).id == REFERENCE_ITEM.stem


@pytest.mark.parametrize("change, reason", [
    (("category: remote-security", "category: made-up"), "unknown category"),
    (("source: original", "source: adapted"), "40-hex"),
    (("id: gb-test-sample", "id: Bad_Id"), "bad id"),
    (("```lua\n--!strict", "```text\n--!strict"), "no ```lua block"),
    (("topics: remotes, validation\n", "topics: x\nextra: 1\n"), "bad front matter"),
])
def test_parse_item_refuses_bad_shapes(change, reason):
    with pytest.raises(ValueError, match=reason):
        gv.parse_item(ITEM.replace(*change, 1))


def test_file_name_must_match_the_id():
    with pytest.raises(ValueError, match="file name"):
        gv.parse_item(ITEM, "data/gold_bank/src/x/other-name.md")


def test_harness_runs_setup_then_the_block_as_a_function_then_the_test():
    item = gv.parse_item(ITEM.replace("local M = {}", "export type T = number\nlocal M = {}"))
    script = gv.harness(item, "-- stubs")
    assert script.index("-- stubs") < script.index("item = (function()") < script.index('check("in range"')
    assert "export type" not in script and "type T = number" in script
    assert script.rstrip().endswith("__done()")


@pytest.mark.parametrize("stdout, rc, verdict", [
    ("@@T\tpass\ta\n@@SUMMARY\t1\t0\n", 0, ""),
    ("@@T\tpass\ta\n@@T\tfail\tb\n@@SUMMARY\t1\t1\n", 0, "failed checks: b"),
    ("@@SUMMARY\t0\t0\n", 0, "no check"),
    ("t.luau:3: attempt to index nil\n", 1, "did not finish"),
])
def test_runtime_verdict(stdout, rc, verdict):
    got = gv.runtime_verdict(stdout, rc)
    assert (got == "") if verdict == "" else (verdict in got)


def test_api_findings_flag_deprecated_and_invented_names_but_not_own_methods():
    from star.roblox_api_dataset import api_dump, load
    dump, dataset = api_dump(), load()
    bad = 'local p = Instance.new("Part")\np.Material = Enum.Material.Shiny\np:BreakJoints()\n'
    found = gv.api_findings(bad, dump, dataset)
    assert any("Material.Shiny" in f for f in found)
    assert any("deprecated member BreakJoints" in f for f in found)
    own = "local Inv = {}\nfunction Inv:BreakJoints() end\nInv:BreakJoints()\nlocal m = Enum.Material.Neon\nreturn m\n"
    assert gv.api_findings(own, dump, dataset) == []


# --- the shipped bank ----------------------------------------------------------------------------------------------

def shipped_rows():
    path = ROOT / "data" / "gold_bank" / "bank.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_shipped_bank_rows_are_valid_verified_and_licence_recorded():
    rows = shipped_rows()
    items = gold_bank.parse_bank((ROOT / "data" / "gold_bank" / "bank.jsonl").read_bytes())
    assert len(items) == len(rows) >= 300
    sources = gv.load_sources()
    licences = (ROOT / "data" / "gold_bank" / "LICENSES.md").read_text(encoding="utf-8")
    for r in rows:
        checks = r["checks"]
        assert all(checks.get(c) == "pass" for c in ("luau", "lint", "api", "slop", "leakage")), r["id"]
        assert checks.get("runtime") in ("pass", "none"), r["id"]
        if r["source"]["kind"] != "original":
            src = sources[r["source"]["source_id"]]
            assert src["accepted"] is True and "GPL" not in src["spdx"].upper()
            assert r["source"]["spdx"] == src["spdx"] and r["source"]["source_id"] in licences
        source_file = ROOT / "data" / "gold_bank" / "src"
        assert any(source_file.rglob(r["id"] + ".md")), r["id"]
    manifest = json.loads((ROOT / "data" / "gold_bank" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["kept"] == len(rows)
    assert manifest["counts"]["written"] == manifest["counts"]["kept"] + manifest["counts"]["dropped"]


def test_shipped_bank_does_not_overlap_the_evaluation_suites():
    """Text-level part of the leakage gate, re-run offline (the embedding part ran at build time)."""
    config, decontam, sim = gv._startrain()
    index = decontam.build_index(gv.EVALS)
    index["items"] = [i for i in index["items"] if not i["source"].startswith("practice-")]
    guard = decontam.Decontaminator(index, config.Settings())
    for r in shipped_rows():
        code = "\n".join(gv.lua_blocks(r["answer"]))
        assert guard.check_text(sim.fingerprint(r["request"], code, "")) == "", r["id"]


def test_training_export_keeps_the_licence_record():
    rows = gv.training_rows([row("gb-x-one", "remote-security", "Ask", kind="adapted", url="https://e/x",
                                 commit="a" * 40, source_id="x", path="f.lua")])
    assert rows[0]["instruction"] == "Ask" and rows[0]["messages"][1]["role"] == "assistant"
    assert rows[0]["licence"]["commit"] == "a" * 40 and rows[0]["source"] == "gold-bank-verified"


# --- retrieval -----------------------------------------------------------------------------------------------------

WORDS = ("datastore", "tween", "remote", "pathfinding")


def fake_vector(text):
    lower = text.lower()
    return [float(lower.count(w)) for w in WORDS] + [0.01]


async def fake_embed(texts):
    return [fake_vector(t) for t in texts]


BANK_ROWS = [
    row("gb-a-save", "datastore-safety", "Save player data in a datastore with retries"),
    row("gb-a-door", "ui-style", "Tween a door open"),
    row("gb-a-remote", "remote-security", "Validate remote arguments on the server"),
]


def test_select_returns_the_closest_items_above_the_floor(tmp_path):
    path = write_bank(tmp_path, BANK_ROWS)
    block, used = asyncio.run(gold_bank.select("How do I save to a datastore safely?", fake_embed, path=path))
    assert [i.id for i in used] == ["gb-a-save"]
    assert block.startswith("[gold example 1: datastore-safety; licence LicenseRef-STAR-Original]")
    assert "Save player data" in block and block.endswith("[end gold example]\n")
    empty, none = asyncio.run(gold_bank.select("Write a poem about rain", fake_embed, path=path))
    assert empty == "" and none == []


def test_select_falls_back_to_words_when_embedding_fails(tmp_path):
    path = write_bank(tmp_path, BANK_ROWS)
    reasons = []

    async def broken(_texts):
        raise ConnectionError("down")

    gold_bank._VECTORS.clear()
    block, used = asyncio.run(gold_bank.select("validate remote arguments server side checks", broken, path=path,
                                               on_fallback=reasons.append))
    assert reasons == ["ConnectionError"] and [i.id for i in used] == ["gb-a-remote"] and block


def test_select_respects_the_budget_and_the_example_cap(tmp_path):
    rows = [row(f"gb-b-{n}", "datastore-safety", f"datastore question {n}", answer="x" * 900) for n in range(6)]
    path = write_bank(tmp_path, rows)
    gold_bank._VECTORS.clear()
    _block, used = asyncio.run(gold_bank.select("datastore", fake_embed, path=path))
    assert len(used) == gold_bank.MAX_EXAMPLES
    small, few = asyncio.run(gold_bank.select("datastore", fake_embed, path=path, max_chars=2100))
    assert len(few) == 2 and len(small) <= 2100
    assert asyncio.run(gold_bank.select("datastore", fake_embed, path=tmp_path / "missing.jsonl")) == ("", [])


def test_bank_rows_are_validated():
    with pytest.raises(ValueError, match="third-party"):
        gold_bank.validate_row(row("gb-c-x", "remote-security", "Q", kind="adapted"))
    with pytest.raises(ValueError, match="unknown category"):
        gold_bank.validate_row(row("gb-c-x", "nope", "Q"))
    unverified = row("gb-c-x", "remote-security", "Q")
    unverified["verified"] = False
    with pytest.raises(ValueError, match="not verified"):
        gold_bank.validate_row(unverified)


def test_setting_is_off_by_default_and_validated():
    from star.desktop_core import Settings
    assert Settings().gold_examples_enabled is False
    with pytest.raises(ValueError):
        Settings(gold_examples_enabled="yes").validate()


def test_run_task_adds_gold_examples_only_with_opt_in_on_roblox_turns(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from star import agent, desktop_core as core
    monkeypatch.setattr(core, "app_data", lambda: tmp_path / "home")
    monkeypatch.setattr(gold_bank, "BANK", write_bank(tmp_path, [
        row("gb-d-save", "datastore-safety", "Save Roblox player data with DataStoreService UpdateAsync retries")]))
    seen, events = [], []

    @asynccontextmanager
    async def model_client(settings, **kwargs):
        yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=None)))

    async def fake_execute(**kwargs):
        seen.append(agent.final_user_text(kwargs["prompt"], agent.volatile_context(
            kwargs["turn_sections"], limit=kwargs["turn_context_chars"])))
        return "answer", [{"role": "assistant", "content": "answer"}], []

    monkeypatch.setattr(core, "open_client", model_client)
    monkeypatch.setattr(core, "execute", fake_execute)
    prompt = "Write a Roblox Luau script that saves player data with DataStoreService UpdateAsync and retries"
    base = core.Settings(model="model", knowledge_endpoint="off")
    assert core.run_task(base, prompt, mode="auto", on_event=events.append) == "answer"
    assert gold_bank.HEADING not in seen[-1]
    base.gold_examples_enabled = True
    assert core.run_task(base, prompt, mode="auto", on_event=events.append) == "answer"
    assert gold_bank.HEADING in seen[-1] and "UpdateAsync retries" in seen[-1]
    used = [e for e in events if e.get("event") == "gold_examples_used"]
    assert used and used[-1]["ids"] == ["gb-d-save"]
    core.run_task(base, "Write a short poem about the sea", mode="auto")
    assert gold_bank.HEADING not in seen[-1]


def test_engine_type_prelude_declares_only_engine_names_the_code_uses():
    from star.roblox_api_dataset import load
    code = "type Vector3 = { x: number }\nlocal function f(p: BasePart, c: CFrame, s: Shop): Player? return nil end\n"
    assert gv.engine_type_prelude(code, load()) == "type BasePart = any; type CFrame = any; type Player = any"
    assert gv.engine_type_prelude("local x = 1\n", load()) == ""


def test_library_calls_are_not_deprecated_instance_members():
    from star.roblox_api_dataset import api_dump, load
    code = "local t = {1, 2}\ntable.remove(t, 1)\nlocal c = table.clone(t)\nreturn c\n"
    assert gv.api_findings(code, api_dump(), load()) == []
