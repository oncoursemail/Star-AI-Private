"""STAR VFX designer: plan prompt + validation, plan -> composer cues, timing curves, the static performance budget and
auto-reduce, the critique -> one fix mapping, the lab census and the whole loop against stand-ins."""
import asyncio
import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from star import roblox_vfx_designer as d
from star import roblox_vfx_studio as vfx

LUAU = vfx.LUAU_DIR


def luau(name: str) -> str:
    return (LUAU / f"{name}.luau").read_text(encoding="utf-8")


def model_plan(**over) -> str:
    plan = {"archetype": "projectile", "style": "realistic_fire", "palette": ["orange", "red"],
            "timing": {"anticipation": 0.6, "impact": 0.1, "follow_through": 1.2}, "scale": 1.2, "intensity": 1.1,
            "extras": ["shake", "nonsense"]}
    plan.update(over)
    return "Sure!\n```json\n" + json.dumps(plan) + "\n```"


# ------------------------------------------------------------------ curves

def test_curves_are_composer_strings_with_endpoints():
    for text in (d.size_fast_in_slow_out(), d.size_grow(), d.alpha_fade(), d.alpha_fade(0, 0.7, 0.3)):
        points = d.curve_points(text)
        assert points[0][0] == 0 and points[-1][0] == 1
        assert [t for t, _ in points] == sorted(t for t, _ in points)
        assert len(points) <= 20 and re.fullmatch(r"[0-9. -]+", text)
    pop = d.curve_points(d.size_fast_in_slow_out(start=0.1, peak_at=0.12, end=0))
    assert pop[1] == (0.12, 1.0) and pop[-1][1] == 0 and pop[0][1] == 0.1
    fade = d.curve_points(d.alpha_fade(0.1, 0.6, 0.2))
    assert fade == [(0, 1), (0.1, 0.2), (0.6, 0.2), (1, 1)]
    assert d.heat_ramp("core", "glow", "dark") == "0 core 0.5 glow 1 dark"
    with pytest.raises(ValueError):
        d.heat_ramp("core", "purple")
    assert d.curve_mean("0 0 1 1", 9) == pytest.approx(0.5)
    assert d.curve_mean(None, 0.4) == 0.4


# ------------------------------------------------------------------ plan

def test_plan_prompt_lists_the_menu_and_the_brief():
    messages = d.plan_prompt("a purple portal")
    text = messages[-1]["content"]
    assert "a purple portal" in text
    for name in (*d.ARCHETYPES, *vfx.STYLES):
        assert name in text
    assert "JSON" in messages[0]["content"]


def test_normalize_plan_reads_fenced_json_and_clamps():
    plan, problems = d.normalize_plan(model_plan(scale=9, intensity=-1, timing={"anticipation": 0.1, "impact": 3,
                                                                                "follow_through": 1}), "fireball")
    assert problems == [] and plan["source"] == "model"
    assert plan["archetype"] == "projectile" and plan["style"] == "realistic_fire"
    assert plan["scale"] == 2.0 and plan["intensity"] == 0.3
    assert plan["timing"]["impact"] == 0.5
    assert plan["timing"]["anticipation"] == 0.4          # a projectile needs time to fly
    assert plan["extras"] == ["shake"]


def test_normalize_plan_falls_back_to_keywords_and_fixes_bad_fields():
    plan, problems = d.normalize_plan("I cannot do that.", "A lingering green poison gas cloud")
    assert plan["source"] == "keywords" and plan["archetype"] == "cloud" and problems
    plan, problems = d.normalize_plan(model_plan(archetype="tornado", style="vaporwave", palette=["#zz0000"]),
                                      "a red laser beam")
    assert plan["archetype"] == "beam" and plan["style"] in vfx.STYLES and plan["palette"] == ["red"]
    assert len(problems) == 3
    plan, _ = d.normalize_plan(model_plan(archetype="laser", palette=["electric blue", "#ff00aa"]), "x")
    assert plan["archetype"] == "beam" and plan["palette"] == ["electric blue", "#ff00aa"]
    loop, _ = d.normalize_plan(model_plan(archetype="portal", timing={"follow_through": 1.0}), "x")
    assert loop["timing"]["follow_through"] == 3.0       # loops stay on screen


def test_palette_maps_main_second_and_dark_colours():
    palette = d.palette_for("anime_energy", ["purple", "#ffcc00", "white"])
    assert palette["glow"] == vfx.COLOUR_WORDS["purple"] and palette["accent"] == (255, 204, 0)
    assert max(palette["dark"]) <= 0.35 * 255 + 1     # a light third colour is kept dark for smoke and cracks
    assert set(palette) == {"core", "glow", "dark", "accent", "flash"}


# ------------------------------------------------------------------ compose

@pytest.mark.parametrize("archetype", list(d.ARCHETYPES))
def test_every_archetype_composes_to_valid_lintable_luau(archetype):
    a, i, f = d.TIMING[archetype]
    plan = {"archetype": archetype, "style": "anime_energy", "palette": ["cyan"], "scale": 1.0, "intensity": 1.0,
            "timing": {"anticipation": a, "impact": i, "follow_through": f}, "extras": list(d.EXTRAS)}
    spec = d.compose(plan, textures={"flipbook": "rbxassetid://95731676298874"})
    cues = spec["ability"]["cues"]
    assert vfx.validate_ability(spec["ability"]) == []
    assert all(c["fx"] in vfx.FX for c in cues)
    assert all(len(c["params"] or {}) <= 24 for c in cues)
    module = vfx.generated_module(spec["style"], spec["ability"], intensity=spec["intensity"], textures=spec["textures"])
    assert "timing = {" in module and "sizeScale = 1.0" in module
    findings = vfx.lint_sources({"VfxGenerated": module})["VfxGenerated"]
    assert not [f for f in findings if f["severity"] == "error"]
    assert spec["effect_length"] == pytest.approx(vfx.style_length("anime_energy", spec["style"]["timing"]), abs=1e-3)


def test_stage_lengths_put_the_follow_through_after_the_hit():
    lengths = d.stage_lengths({"anticipation": 0.3, "impact": 0.1, "follow_through": 2.0})
    times = vfx.stage_times("anime_energy", lengths)
    assert times["impact"] == 0.3 and times["finish"] - times["shockwave"] == pytest.approx(2.0)


def test_python_timing_override_matches_the_luau_composer():
    styles = luau("VfxStyles")
    assert "local timing = fields.timing" in styles and "math.clamp(timing[key], 0.02, 10)" in styles
    assert vfx.style_length("anime_energy", {"charge": 1.0}) == pytest.approx(vfx.style_length("anime_energy") + 0.1)


def test_new_primitives_are_data_only_and_registered():
    prims, composer = luau("VfxPrimitives"), luau("VfxComposer")
    for name in ("particles", "beam", "projectile", "sweep"):
        assert f"function Prim.{name}(ctx: Ctx, p: Params?)" in prims
        assert f"{name} = Prim.{name}," in composer
    for word in ("loadstring", "require(", "HttpService"):
        assert word not in prims.split("data-driven layers")[1] or word == "require("
    assert "FlipbookLayout = Enum.ParticleFlipbookLayout.Grid4x4" in prims
    assert "CurveSize0" in prims and "TextureSpeed" in prims and "WidthScale" in prims and "MinLength" in prims


def test_style_light_mirror_matches_the_luau_profiles():
    styles = luau("VfxStyles")
    for name, value in d.STYLE_LIGHT.items():
        block = styles[styles.index(f"Styles.{name} = "):]
        assert re.search(r"lightEmission = ([0-9.]+)", block).group(1) == f"{value:g}", name


# ------------------------------------------------------------------ budget

def _style(**over):
    return {"base": "anime_energy", "timing": d.stage_lengths({"anticipation": 0.2, "impact": 0.1,
                                                               "follow_through": 1.0}), "sizeScale": 1.0, **over}


def test_budget_counts_bursts_and_loops():
    cues = [d._c("impact", 0, "particles", count=50, life=1.0, size=2, sizeCurve="0 1 1 1", alphaCurve="0 0 1 0"),
            d._c("charge", 0, "particles", rate=100, dur=1.0, life=0.5, size=1)]
    report = d.check_budget(cues, _style())
    assert report["live_sum"] == round(50 + 100 * 0.5 * 0.85)
    assert report["live_peak"] >= 50
    one = d.check_budget(cues[:1], _style())
    expected = 50 * (2 * d.PX_PER_STUD) ** 2 * 1.0 / (1920 * 1080)
    assert one["overdraw_peak"] == pytest.approx(expected, rel=0.01)
    assert one["additive_peak"] == 1 and one["ok"]
    mobile = d.check_budget(cues, _style(), platform="mobile")
    assert mobile["live_peak"] < report["live_peak"]          # composer quality 0.5 on phones


def test_budget_flags_and_auto_reduce_fixes_an_overloaded_effect():
    heavy = [d._c("charge", 0, "particles", rate=900, dur=3, life=3, size=6, sizeCurve="0 1 1 1"),
             d._c("impact", 0, "light", dur=1), d._c("impact", 0, "particles", count=400, life=1, size=8)]
    report = d.check_budget(heavy, _style())
    assert not report["ok"]
    text = " ".join(report["findings"])
    assert "live particles" in text and "overdraw" in text and "rate" in text and "composer cap" in text
    cues, after, actions = d.auto_reduce(heavy, _style())
    assert actions and after["live_peak"] <= d.BUDGETS["pc"]["live"]
    assert after["overdraw_peak"] <= d.BUDGETS["pc"]["overdraw"] * 1.05
    assert after["requested_particles"] <= after["composer_cap"] * 1.05
    assert cues[1] == heavy[1]                                  # non-particle cues untouched
    light = [d._c("impact", 0, "particles", count=10, size=1)]
    assert d.auto_reduce(light, _style())[2] == []


def test_budget_flags_stacked_glow_and_many_lights():
    cues = [d._c("impact", 0, "particles", count=5, size=1, lightEmission=1, alphaCurve="0 0 1 0") for _ in range(8)]
    cues += [d._c("impact", 0, "light", dur=1) for _ in range(5)]
    report = d.check_budget(cues, _style())
    assert report["additive_peak"] == 8 and report["lights"] == 5
    assert any("whiteout" in f for f in report["findings"]) and any("lights" in f for f in report["findings"])


# ------------------------------------------------------------------ critique -> fix

def test_vision_parse_and_fix_mapping():
    got = d.parse_vision('```json\n{"score": 2, "problems": ["too_small", "too_faint", "made_up"], "note": "tiny"}\n```')
    assert got == {"score": 2, "problems": ["too_small", "too_faint"], "note": "tiny", "parsed": True}
    assert d.parse_vision("no idea")["parsed"] is False
    fix = d.fixes_for({"findings": ["weak impact: x", "the style's main colour is barely visible in effect frames"]},
                      got, realtime=True)
    assert fix == {"scale": 1.35, "intensity": round(1.15 * 1.3, 3)}      # timed finding skipped in real time
    slow = d.fixes_for({"findings": ["weak impact: x"]}, None, realtime=False)
    assert slow == {"intensity": 1.25}
    assert d.fixes_for(None, {"problems": []}) == {}
    plan = {"scale": 1.8, "intensity": 1.0, "timing": {"anticipation": 0.1, "impact": 0.1, "follow_through": 3.5}}
    fixed = d.apply_fixes(plan, {"scale": 1.35, "intensity": 0.75, "follow_through": 1.4})
    assert fixed["scale"] == 2.0 and fixed["intensity"] == 0.75 and fixed["timing"]["follow_through"] == 4.0
    assert plan["scale"] == 1.8                                           # input not mutated


# ------------------------------------------------------------------ lab census, sheet frames

def test_census_is_added_inside_the_lab_client_and_parsed():
    spec = d.lab_spec(d.compose(d.keyword_plan("a heal aura")))
    code = d.with_census(vfx.apply_luau(spec, "abcd1234"))
    lines = code.splitlines()
    assert lines[-1].startswith('return "STARVFX_APPLY abcd1234')
    assert "census.Parent = client" in code and "StarVfxLabCensus" in code
    got = d.parse_census('x\nSTARVFX census {"peak": {"emitters": 2}}\n'
                         'STARVFX census {"peak": {"emitters": 5, "parts": 50}, "first": {"emitters": 0, "parts": 44}}')
    assert got["peak"] == {"emitters": 5, "parts": 50} and got["effect_peak"] == {"emitters": 5, "parts": 6}
    assert d.parse_census("nothing") is None
    with pytest.raises(ValueError):
        d.with_census("print(1)")


def test_sheet_frames_drop_the_idle_wait_and_lab_timing_is_shared():
    frames = [{"index": i, "effect_t": t} for i, t in enumerate([-3, -2, -1, 0.2, 0.8])]
    assert [f["index"] for f in d.sheet_frames(frames)] == [2, 3, 4]
    spec = d.lab_spec({"style": {"base": "anime_energy"}, "ability": {"name": "impact_hit", "builtin": True}})
    assert spec["speed"] == 1.0 and spec["length"] == d.PERIOD and spec["timer"] is False
    assert "length = 4.5" in vfx.lab_config(spec, "run1")


def _jpeg(colour) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(out, "JPEG")
    return out.getvalue()


class FakeLab:
    def __init__(self, out: Path):
        self.out = out
        self.codes = []

    async def _luau(self, code):
        self.codes.append(code)
        run = re.search(r'return "STARVFX_APPLY (\w+)', code).group(1)
        return True, f"STARVFX_APPLY {run} 6"

    async def _playtest(self, spec, run):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "playtest-output.txt").write_text('STARVFX census {"peak": {"emitters": 3}}', encoding="utf-8")
        frames = [{"index": i, "effect_t": t, "data": _jpeg((20 * i, 40, 200 if t > 0 else 40))}
                  for i, t in enumerate([-0.5, 0.1, 0.6, 1.2, 2.5])]
        return {"ok": True, "frames": len(frames), "_frames": frames, "frame_files": []}


def test_render_spec_against_a_stand_in_lab(tmp_path):
    lab = FakeLab(tmp_path / "r1")
    spec = d.lab_spec(d.compose(d.keyword_plan("a fireball projectile")))
    report = asyncio.run(d.render_spec(lab, spec, "feedbeef", title="brief-1"))
    assert report["apply"]["ok"] and report["frames"] == 5 and report["census"]["effect_peak"] == {"emitters": 3}
    assert Path(report["sheet_path"]).exists() and "critique" in report
    assert "StarVfxLabCensus" in lab.codes[0]
    assert json.loads((tmp_path / "r1" / "render.json").read_text())["run"] == "feedbeef"


def test_make_effect_runs_at_most_one_fix_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vfx, "critique", lambda frames, style: {"ok": True, "findings": [], "scores": {}})
    calls = {"render": [], "vision": 0}

    def chat(messages):
        return model_plan(), 1.5

    def vision(prompt, sheet):
        calls["vision"] += 1
        assert "fireball" in prompt and sheet.exists()
        return '{"score": 2, "problems": ["too_small"], "note": "small"}', 120.0

    async def render(spec, tag):
        calls["render"].append((tag, spec["style"]["sizeScale"]))
        return await d.render_spec(FakeLab(tmp_path / tag), d.lab_spec(spec), "aa11bb22")

    record = asyncio.run(d.make_effect("a fireball", chat, render, vision=vision))
    assert calls["vision"] == 1 and [t for t, _ in calls["render"]] == ["r1", "r2"]
    assert calls["render"][1][1] == pytest.approx(min(2.0, 1.2 * 1.35), abs=1e-3)
    assert record["final"] == "render2" and record["review"]["fix"]["scale"] == 1.35
    assert record["budget"]["ok"] and record["plan_s"] == 1.5

    def fine(prompt, sheet):
        return '{"score": 5, "problems": ["fine"]}', 1.0

    calls["render"].clear()
    record = asyncio.run(d.make_effect("a fireball", chat, render, vision=fine))
    assert [t for t, _ in calls["render"]] == ["r1"] and record["final"] == "render1"
    assert record["review"]["critic"] == "vision"

    asked = []

    def text_critic(messages):
        if "Measured facts" in messages[-1]["content"]:
            asked.append(messages)
            return '{"score": 2, "problems": ["too_faint"]}', 3.0
        return model_plan(), 1.5

    calls["render"].clear()
    record = asyncio.run(d.make_effect("a fireball", text_critic, render, vision=lambda p, s: ("", 0.0)))
    assert asked and record["review"]["critic"] == "text-facts"
    assert record["review"]["fix"] == {"intensity": 1.3} and record["final"] == "render2"
