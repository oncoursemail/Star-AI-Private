"""The experimental roblox-secondary-motion-lab pack: registered like the other packs, but off by default."""
from star import skill_packs

NAME = "roblox-secondary-motion-lab"
PROMPT = "In Roblox, add SmartBone-style secondary motion to my character's ponytail with an XPBD solver."


def test_pack_is_shipped_and_labelled_experimental():
    pack = next(p for p in skill_packs.available() if p.name == NAME)
    assert pack.description.startswith("EXPERIMENTAL")
    assert "EXPERIMENTAL" in pack.body.splitlines()[0]
    assert (pack.file.parent / "assets" / "StarSpringXPBD.luau").is_file()


def test_pack_is_off_until_the_owner_opts_in():
    assert NAME not in skill_packs.DEFAULT_ENABLED and NAME not in skill_packs.enabled_names({})
    assert NAME not in skill_packs.matching_names(PROMPT)
    assert skill_packs.enabled_names({skill_packs.ENV_VAR: NAME}) == {NAME}
    assert skill_packs.matching_names(PROMPT, enabled={NAME}) == [NAME]


def test_pack_needs_a_roblox_question_that_names_its_topic():
    assert skill_packs.matching_names("Explain XPBD cloth physics for my C++ engine", enabled={NAME}) == []
    assert skill_packs.matching_names("In Roblox Studio, how do I place a part?", enabled={NAME}) == []
