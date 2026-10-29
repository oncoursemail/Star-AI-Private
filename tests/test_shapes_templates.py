"""Blockbench part templates (star/shapes/bb.py) and the shared planner (star/shapes/core.py). No network."""
import json
import random

import pytest

from star.blockbench import build as B
from star.blockbench import checks as C
from star.blockbench import spec as S
from star.shapes import a3d, bb, core
from star.shapes import pipeline as SP

NAMES = list(bb.TEMPLATES)


def _answers(t, n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        params = {}
        for k, p in t.params.items():
            if p.kind == "enum":
                params[k] = rng.choice(list(p.choices) + ["garbage"])
            elif p.kind == "bool":
                params[k] = rng.choice([True, False, "yes", 0])
            else:
                params[k] = rng.choice([p.lo, p.hi, (p.lo + p.hi) / 2, p.lo - 50, p.hi + 50, "x", None])
        colors = {r: rng.choice(["#a03030", "zz", "4080c0", None]) for r in t.roles}
        yield {"params": params, "colors": colors, "kinds": {r: rng.choice(bb.KINDS + ("nope",)) for r in t.roles}}


def _build_ok(name, answer):
    raw, _ = bb.build_spec(name, answer)
    spec, _ = S.normalize(raw)
    built = B.build(spec)
    rep = C.check(built["bbmodel"])
    codes = {f["code"] for f in rep["findings"] if f["severity"] == "error"}
    return spec, rep, codes


@pytest.mark.parametrize("name", NAMES)
def test_template_defaults_build_clean(name):
    spec, rep, codes = _build_ok(name, None)
    assert spec["category"] == bb.TEMPLATES[name].category
    assert len(spec["parts"]) <= S.PART_LIMIT[spec["category"]]
    allowed = {"floating-parts"} if name == "totem" else set()  # the totem's crystal hovers on purpose
    assert codes <= allowed, (name, rep["findings"])
    if S.model_format(spec["category"]) == "bedrock" and name not in ("armor",):
        assert spec["animations"], name


@pytest.mark.parametrize("name", NAMES)
def test_template_survives_random_and_garbage_answers(name):
    t = bb.TEMPLATES[name]
    for ans in _answers(t, 12, hash(name) & 0xFFFF):
        spec, rep, codes = _build_ok(name, ans)
        assert len(spec["parts"]) <= S.PART_LIMIT[spec["category"]] + 8, name
        assert "uv-out-of-bounds" not in codes


def test_mirror_pairs_are_symmetric():
    raw, _ = bb.build_spec("quadruped", None)
    parts = {p["name"]: p for p in S.normalize(raw)[0]["parts"]}
    for n, p in parts.items():
        if n.endswith("_r") and n[:-2] + "_l" in parts:
            q = parts[n[:-2] + "_l"]
            assert p["from"][0] == -q["to"][0] and p["to"][0] == -q["from"][0], n
            assert p["from"][1:] == q["from"][1:] and p["to"][1:] == q["to"][1:], n


def test_param_coercion_and_resolve():
    t = bb.TEMPLATES["chair"]
    params, roles, notes = core.resolve(t, {"params": {"style": "Armchair", "width": 99, "trim": "yes", "bogus": 1},
                                            "colors": {"cushion": "7a2030", "frame": "red"},
                                            "kinds": {"cushion": "wool", "frame": "lava"}}, bb.KINDS)
    assert params["style"] == "armchair" and params["width"] == 20 and params["trim"] is True
    assert roles["cushion"] == {"color": "#7a2030", "kind": "wool"}
    assert roles["frame"]["color"] == t.roles["frame"].color and roles["frame"]["kind"] == t.roles["frame"].kind
    assert any("ignored" in n for n in notes)


def test_keyword_fallback_picks_shape():
    assert core.pick_by_keywords(bb.TEMPLATES, "a woolly sheep") == "quadruped"
    assert core.pick_by_keywords(bb.TEMPLATES, "an old oak bookshelf") == "shelf"
    assert core.pick_by_keywords(a3d.TEMPLATES, "a bolt-action rifle") == "firearm"


@pytest.mark.parametrize("mod", [bb, a3d])
def test_prompts_fit_the_node_context(mod):
    # 4096-token node context: system+user of each call must stay far below it (~3.5 chars per token)
    pick = sum(len(m["content"]) for m in core.pick_prompt(mod.TEMPLATES, "x" * 200, "Category: mob"))
    assert pick / 3.0 < 1500
    for t in mod.TEMPLATES.values():
        fill = sum(len(m["content"]) for m in core.fill_prompt(t, "x" * 200, mod.KINDS, "Category: mob"))
        assert fill / 3.0 < 1500, t.name


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, 0.1, {}


def test_plan_uses_answers_and_falls_back():
    good = FakeLLM(['{"template": "bird"}', '```json\n{"name": "Penguin!", "params": {"posture": "upright", "belly": true},'
                                            ' "colors": {"body": "#202830"},}\n```'])
    pl = core.plan(good, "a waddling penguin", bb.TEMPLATES, bb.KINDS)
    assert pl["template"] == "bird" and pl["params"]["posture"] == "upright" and pl["name"] == "penguin"
    assert pl["roles"]["body"]["color"] == "#202830"
    bad = FakeLLM([RuntimeError("503 mesh busy"), "not json at all"])
    pl = core.plan(bad, "a wooden dining table", bb.TEMPLATES, bb.KINDS)
    assert pl["template"] == "table" and pl["params"] == {k: p.default for k, p in bb.TEMPLATES["table"].params.items()}
    odd = FakeLLM(['{"template": "spaceship"}', '{"params": {}}'])
    assert core.plan(odd, "a hanging lantern", bb.TEMPLATES, bb.KINDS)["template"] == "lantern"


def test_make_bb_writes_valid_files(tmp_path):
    llm = FakeLLM(['{"template": "lantern"}', json.dumps({"name": "chain_lantern", "params": {"hanging": True}})])
    pl = SP.make_bb(llm, "a hanging lantern", "block", tmp_path)
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rep["template"] == "lantern" and rep["checks"] >= 70
    bbm = json.loads(next(tmp_path.glob("*.bbmodel")).read_text(encoding="utf-8"))
    assert bbm["meta"]["model_format"] == "java_block" and len(bbm["elements"]) == len(pl["spec"]["parts"])
    assert next(tmp_path.glob("*_views.png")).stat().st_size > 1000
