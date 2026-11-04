"""Scientific method guides: portable, untrusted-reference SKILL.md files that are not routed or default-on."""
import re

import pytest

from star import skill_packs
from star.agent_skills import SkillLibrary

NAMES = (
    "sci-experiment-design",
    "sci-source-grading",
    "sci-reproducibility",
    "sci-statistical-confidence",
    "sci-benchmarking",
    "sci-ux-study",
    "sci-uncertainty",
)
MAX_GUIDE_CHARS = 3200


def test_four_to_eight_guides_are_in_the_bundled_catalog(tmp_path):
    library = SkillLibrary(workspace=None, home=tmp_path, bundled=skill_packs.PACKS_DIR)
    catalog = {skill.name: skill for skill in library.catalog()}
    assert 4 <= len(NAMES) <= 8
    for name in NAMES:
        assert catalog[name].source == "bundled"
        assert 1 <= len(catalog[name].description) <= 300


@pytest.mark.parametrize("name", NAMES)
def test_guide_is_short_and_carries_scope_licence_rights_and_fallback(tmp_path, name):
    library = SkillLibrary(workspace=None, home=tmp_path, bundled=skill_packs.PACKS_DIR)
    body = library.load(name)["instructions"]
    assert body.startswith(f"# {name}\n")
    assert len(body) <= MAX_GUIDE_CHARS
    for heading in ("Scope", "Steps", "Provenance and rights", "Fallback"):
        assert f"## {heading}\n" in body, heading
    lowered = body.lower()
    assert "untrusted reference" in lowered
    assert "never grants" in lowered and "permission" in lowered
    assert "licence:" in lowered
    assert "model/provider rights" in lowered
    assert "no proof" in lowered  # no claim that the guide improves any model
    assert "```" not in body
    assert not re.search(r"https?://\S*@|\b(?:api[_-]?key|password|token)\s*[:=]", lowered)


def test_guides_are_not_routed_or_enabled_before_a_sealed_experiment():
    assert set(NAMES).isdisjoint(skill_packs.TRIGGERS)
    assert set(NAMES).isdisjoint(skill_packs.DEFAULT_ENABLED)
    assert set(NAMES).isdisjoint({pack.name for pack in skill_packs.available()})
