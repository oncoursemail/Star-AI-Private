"""Anti-slop packs (star/antislop.py, star/skill_packs/antislop*): routing, budget, loader, provenance."""
from __future__ import annotations

from star import antislop, skill_packs
from star.agent_skills import _frontmatter

NAMES = ("antislop", "antislop-code", "antislop-copywriting", "antislop-human", "antislop-layoutmobile", "antislop-ui")


def test_every_pack_loads_with_plain_frontmatter():
    for name in NAMES:
        folder = skill_packs.PACKS_DIR / name
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        fields, body = _frontmatter(text)
        assert fields["name"] == name and fields["description"]
        assert "allowed-tools" not in text.split("\n---\n", 1)[0]
        assert len(body) > 2000                          # the verbatim upstream text, not a stub
        assert antislop._digest(name).startswith("# Anti-slop")
        assert "miqdadbadjuber/anti-slop" in (folder / "references" / "SOURCE.md").read_text(encoding="utf-8")


def test_notices_carry_the_licence():
    text = (skill_packs.PACKS_DIR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "miqdadbadjuber/anti-slop" in text and "Copyright (c) 2026 Miqdad Badjuber" in text and "3.2.21" in text


def test_ui_request_selects_core_and_ui():
    assert antislop.select("Build a landing page for my bakery with a hero section and a navbar") == ["antislop", "antislop-ui"]


def test_specialised_topics():
    assert antislop.select("Make this layout responsive on mobile, the grid has horizontal overflow") == [
        "antislop", "antislop-layoutmobile"]
    assert antislop.select("Check the WCAG contrast and keyboard navigation of my form") == ["antislop", "antislop-human"]
    assert antislop.select("Write a tagline and marketing copy for our app") == ["antislop", "antislop-copywriting"]


def test_code_request_selects_code():
    assert antislop.select("Write a Python function that parses a CSV file") == ["antislop", "antislop-code"]
    assert antislop.select("Remove the pointless docstrings from this module") == ["antislop", "antislop-code"]


def test_plain_chat_and_game_prompts_select_none():
    for prompt in ("What is the capital of France?", "Explain how a mutex works", "hello", "", None,
                   "Write a Roblox script with a ScreenGui button", "Make a Godot UI theme for my game",
                   "Write a function in Bevy for the player UI"):
        assert antislop.select(prompt) == [], prompt


def test_switch_off():
    assert antislop.select("Build a landing page", environ={"STAR_ANTISLOP": "off"}) == []


def test_block_is_small_and_headed():
    block = antislop.render(antislop.select("Build a landing page for my bakery"))
    assert block and len(block) <= antislop.MAX_BLOCK_CHARS
    assert "Purpose test" in block and "Anti-slop UI" in block
    assert antislop.render([]) == ""
