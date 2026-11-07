"""API member hints (star/api_hints.py) from the bundled Roblox API dump, and the opt-in turn section."""
import pytest

from star import api_hints
from star.slop import bundled_api_dump


@pytest.fixture(scope="module")
def dump():
    return bundled_api_dump()


def test_classes_are_found_by_exact_spelling_in_order_and_capped(dump):
    prompt = ("Build a shop with a UIGridLayout inside a ScrollingFrame; the Atmosphere stays moody. "
              "Players join through Players; textlabel and Partt are not classes.")
    assert api_hints.classes_in(prompt, dump) == ["UIGridLayout", "ScrollingFrame", "Atmosphere", "Players"]
    assert api_hints.classes_in("Part Part Part", dump) == ["Part"]
    assert api_hints.classes_in("nothing here", dump) == []
    many = " ".join(["Part", "Model", "Folder", "Script", "Humanoid", "Tool", "Sound", "Beam"])
    assert len(api_hints.classes_in(many, dump)) == api_hints.MAX_CLASSES


def test_members_list_the_real_spellings_own_first_without_internal_names(dump):
    grid = api_hints.members_of("UIGridLayout", dump)
    assert grid[:6] == ["AbsoluteCellCount", "AbsoluteCellSize", "CellPadding", "CellSize", "FillDirectionMaxCells", "StartCorner"]
    assert "FillDirection" in grid and "ColumnCount" not in grid and "Spacing" not in grid
    atmosphere = api_hints.members_of("Atmosphere", dump)
    assert atmosphere == ["Color", "Decay", "Density", "Glare", "Haze", "Offset"]     # no Instance members, no SunInfluence
    players = api_hints.members_of("Players", dump)
    assert "PlayerAdded" in players and "GetPlayers" in players
    assert not any(m.endswith("ConnectionCount") or m[0].islower() for m in api_hints.members_of("TextLabel", dump))
    assert len(api_hints.members_of("TextLabel", dump)) == api_hints.MAX_MEMBERS


def test_the_block_is_one_line_per_class_bounded_and_empty_without_classes(dump):
    block = api_hints.hint_block("Set the Atmosphere density and list Players", dump)
    assert block.splitlines()[0] == "Atmosphere: Color, Decay, Density, Glare, Haze, Offset"
    assert block.splitlines()[1].startswith("Players (service): ")
    assert api_hints.hint_block("hello", dump) == ""
    long = api_hints.hint_block("TextLabel TextButton ImageLabel Frame ScrollingFrame Humanoid", dump)
    assert len(long) <= api_hints.MAX_CHARS + 5 and long.endswith(", ...")


def test_the_setting_is_off_by_default_and_validated():
    from star.desktop_core import Settings
    assert Settings().api_hints_enabled is False
    with pytest.raises(ValueError):
        Settings(api_hints_enabled="yes").validate()
