import re

import pytest

from star import roblox_lighting_presets as lp

REQUIRED_WHY = ("lighting.Ambient", "lighting.Brightness", "lighting.ClockTime", "lighting.ExposureCompensation",
                "atmosphere.Density", "post.ColorCorrection", "post.Bloom")


def _balanced(luau: str) -> bool:
    code = re.sub(r'"(\\.|[^"\\])*"', '""', luau)
    code = re.sub(r"--[^\n]*", "", code)
    words = re.findall(r"[A-Za-z_]+", code)
    opens = sum(w in ("function", "do", "then") for w in words) - words.count("elseif")
    return opens == words.count("end")


def test_kelvin_to_rgb_shape():
    assert lp.kelvin_to_rgb(6600) == [255, 255, 255]
    warm, cool = lp.kelvin_to_rgb(2700), lp.kelvin_to_rgb(10000)
    assert warm[0] == 255 and warm[2] < 180
    assert cool[2] == 255 and cool[0] < 220
    assert lp.kelvin_to_rgb(-5) == lp.kelvin_to_rgb(1000)


@pytest.mark.parametrize("name", lp.PRESET_NAMES)
def test_every_preset_is_complete_and_compiles(name):
    p = lp.PRESETS[name]
    assert len(lp.PRESET_NAMES) >= 8 and "moody_night_diner_teal" in lp.PRESET_NAMES
    for key in REQUIRED_WHY:
        assert p["why"].get(key), (name, key)
    assert set(p["practicals"]) == set(lp.ROLES)
    for role, recipe in p["practicals"].items():
        assert recipe.get("why"), (name, role)
    assert {"mean_luma", "crushed_max", "clipped_max", "contrast", "warmth", "saturation"} <= set(p["targets"])
    assert p["clock_range"][0] <= p["lighting"]["ClockTime"] <= p["clock_range"][1] or p["lighting"]["ClockTime"] == 0
    luau = lp.lighting_luau(name)
    assert _balanced(luau)
    assert 'ServerStorage:FindFirstChild("StarLightingBackup")' in luau
    assert "Lighting.Ambient = Color3.fromRGB(" in luau and luau.rstrip().endswith(")")
    assert "return string.format" in luau
    assert lp.lighting_luau(name) == luau  # deterministic


def test_overrides_are_clamped_and_validated():
    luau = lp.lighting_luau("bright_stylized_day", {"lighting.ExposureCompensation": 99,
                                                    "post.ColorCorrection.TintColor": [300, -4, 10]})
    assert "Lighting.ExposureCompensation = 3.0" in luau
    assert "TintColor = Color3.fromRGB(255, 0, 10)" in luau
    with pytest.raises(ValueError):
        lp.lighting_luau("bright_stylized_day", {"post.DepthOfField.FarIntensity": 0.5})  # DoF is None here
    with pytest.raises(ValueError):
        lp.lighting_luau("bright_stylized_day", {"lighting.Nonsense": 1})
    with pytest.raises(ValueError):
        lp.lighting_luau("nope")
    with pytest.raises(ValueError):
        lp.lighting_luau("bright_stylized_day", root='workspace"); os.exit()--')


def test_practical_recipes_compile_to_lights():
    luau = lp.lighting_luau("warm_luxury_interior", root="workspace.StarUiVfxLighting")
    assert 'sconce = {class = "SpotLight"' in luau and 'face = "Top"' in luau
    assert '{"StarUiVfxLighting"}' in luau
    day = lp.lighting_luau("bright_stylized_day")
    assert "pendant = {" not in day  # practicals off by day


def test_restore_luau():
    luau = lp.restore_luau("workspace.StarUiVfxLighting")
    assert _balanced(luau)
    assert "StarPracticalLight" in luau and "StarPrevColor" in luau and "backup:Destroy()" in luau


def test_plan_prompt_lists_presets_and_parse_plan():
    prompt = lp.plan_prompt("foggy graveyard")
    for name in lp.PRESET_NAMES:
        assert name in prompt
    assert '"foggy graveyard"' in prompt
    assert lp.parse_plan('```json\n{"preset": "x", "a": {"b": "}"}}\n```') == {"preset": "x", "a": {"b": "}"}}
    assert lp.parse_plan("Sure! {bad} then {\"preset\": \"y\"} done") == {"preset": "y"}
    assert lp.parse_plan("no json") == {}


def test_apply_plan_clamps_and_maps_deterministically():
    plan = {"preset": "moody_night_diner", "warmth": 5, "contrast": "0.5", "saturation": None, "fog": -1,
            "time_of_day": 12, "key_light_color": "#FF0000"}
    a, b = lp.apply_plan(plan), lp.apply_plan(plan)
    assert a == b
    assert a["plan"]["warmth"] == 1.0 and a["plan"]["contrast"] == 0.5 and a["plan"]["saturation"] == 0.0
    assert a["lighting"]["ClockTime"] == 4  # snapped into the preset's 0-4 band
    base = lp.PRESETS["moody_night_diner"]
    assert a["post"]["ColorCorrection"]["TintColor"][2] < base["post"]["ColorCorrection"]["TintColor"][2]
    assert a["lighting"]["Ambient"][0] < base["lighting"]["Ambient"][0]
    assert a["atmosphere"]["Density"] < base["atmosphere"]["Density"]
    assert a["practicals"]["pendant"]["color"] == [255, 0, 0]
    assert lp.apply_plan({"preset": "neon_cyber_night", "time_of_day": 1})["lighting"]["ClockTime"] == 0
    assert lp.apply_plan({"preset": "golden_hour_exterior", "time_of_day": "dusk"})["lighting"]["ClockTime"] == 18.2
    assert _balanced(lp.lighting_luau(a))


def test_apply_plan_fallback_uses_brief():
    p = lp.apply_plan({"preset": "made_up"}, brief="cyberpunk alley")
    assert p["name"] == "neon_cyber_night" and p["notes"]
    assert lp.apply_plan("garbage", brief="")["name"] == "bright_stylized_day"


def test_analyze_render_metrics():
    Image = pytest.importorskip("PIL.Image")
    black = lp.analyze_render(Image.new("RGB", (64, 32), (0, 0, 0)))
    assert black["crushed_pct"] == 100 and black["mean_luma"] == 0
    white = lp.analyze_render(Image.new("RGB", (64, 32), (255, 255, 255)))
    assert white["clipped_pct"] == 100
    img = Image.new("RGB", (100, 10), (0, 0, 0))
    img.paste((240, 140, 60), (50, 0, 100, 10))
    m = lp.analyze_render(img)
    assert m["warmth"] > 0.3 and m["contrast"] > 100 and m["saturation"] > 0.6
    assert 40 < m["mean_luma"] < 90


def test_suggest_fix_one_iteration_and_luau_accepts_it():
    p = lp.resolve("warm_luxury_interior")
    dark = {"mean_luma": 20.0, "crushed_pct": 60.0, "clipped_pct": 0.0, "p5": 0, "p95": 90, "contrast": 90,
            "warmth": 0.0, "saturation": 0.2}
    over, why = lp.suggest_fix(dark, p)
    assert over["lighting.ExposureCompensation"] > p["lighting"]["ExposureCompensation"]
    assert "post.ColorCorrection.TintColor" in over and "post.ColorCorrection.Contrast" in over and why
    assert lp.suggest_fix(dark, p, iteration=1)[0] == {}
    assert "Lighting.ExposureCompensation = " in lp.lighting_luau(p, over)
    ok = {"mean_luma": 70.0, "crushed_pct": 10.0, "clipped_pct": 1.0, "p5": 5, "p95": 180, "contrast": 175,
          "warmth": 0.2, "saturation": 0.4}
    assert lp.check_render(ok, p) == [] and lp.suggest_fix(ok, p)[0] == {}
