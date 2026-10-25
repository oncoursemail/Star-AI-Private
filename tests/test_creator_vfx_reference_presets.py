"""Video-inspired but original VFX cue presets: readable timing and safe budgets."""
import pytest

from star import roblox_vfx_studio as vfx


@pytest.mark.parametrize(("prompt", "name", "stages"), [
    ("blue ice vortex crystal storm", "frost_cyclone",
     {"charge", "impact", "shockwave", "linger", "dissipate"}),
    ("anime sword slash with bright orange blade trail", "cinematic_sword_arc",
     {"charge", "impact", "shockwave", "linger", "dissipate"}),
])
def test_reference_ability_cues_are_bounded_and_valid(prompt, name, stages):
    ability = vfx.choose_ability(prompt)
    assert ability["name"] == name and ability["builtin"] is False
    assert vfx.validate_ability(ability) == []
    assert {cue["stage"] for cue in ability["cues"]} == stages
    assert len(ability["cues"]) <= 20
    assert sum(cue["params"].get("count", 0) for cue in ability["cues"]
               if isinstance(cue.get("params"), dict)) <= 240
    style = vfx.choose_style(prompt)
    generated = vfx.generated_module(style, ability)
    assert name in generated


def test_sword_hit_legacy_routing_preserved():
    assert vfx.choose_ability("sword hit impact")["name"] == "impact_hit"


def test_ice_palette_inherits_approved_recolouring_path():
    style = vfx.choose_style("ice vortex")
    assert style["palette"] is not None
    assert style["palette"]["glow"] == vfx.COLOUR_WORDS["ice"]


def test_sword_slash_without_extra_words_selects_new_preset():
    assert vfx.choose_ability("sword slash")["name"] == "cinematic_sword_arc"
