"""Regression checks for the opt-in Studio MCP/Open Cloud skill guidance."""
from pathlib import Path

from star import skill_packs


def _pack():
    return next(
        item for item in skill_packs.available()
        if item.name == "roblox-studio-mcp-workflow"
    )


def test_studio_mcp_permission_guidance_remains_opt_in():
    pack = _pack()
    assert pack.name not in skill_packs.DEFAULT_ENABLED
    assert len(pack.body) <= skill_packs.MAX_BODY_CHARS


def test_explicit_opt_in_routes_a_studio_mcp_permission_prompt():
    pack = _pack()
    selected = skill_packs.select(
        "Roblox Studio MCP Open Cloud permissions",
        enabled=frozenset({pack.name}),
    )
    assert [item.name for item in selected] == [pack.name]


def test_studio_mcp_permissions_are_per_game_and_person_controlled():
    body = _pack().body.lower()
    for required in (
        "open_cloud_invoke",
        "per game and per person",
        "each collaborator manages their own permission set",
        "safe or a narrow custom selection",
        "full access",
        "exact missing permission",\n        "client cannot enable or widen those permissions",
    ):
        assert required in body


def test_live_data_and_network_capabilities_have_separate_guards():
    body = _pack().body.lower()
    assert "separate private test experience" in body
    assert "live data stores" in body
    assert "network capability" in body
    assert "explicit domain allowlist" in body
    assert "approved" in body and "folders" in body


def test_permission_sources_are_official_and_current():
    path = Path(__file__).resolve().parents[1] / "star" / "skill_packs" / "roblox-studio-mcp-workflow" / "references" / "sources.md"
    sources = path.read_text(encoding="utf-8")
    assert "permissions reviewed 2026-11-10" in sources
    assert "https://create.roblox.com/docs/studio/mcp-open-cloud" in sources
    assert "https://create.roblox.com/docs/cloud/reference/scopes" in sources
    assert "https://create.roblox.com/docs/cloud-services/data-stores" in sources
