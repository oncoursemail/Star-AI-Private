import asyncio
import json

from star.project_catalog import project_catalog, project_for_repository


def test_owner_names_are_exact_and_repositories_are_separate():
    projects = project_catalog()["projects"]
    assert [(p["name"], p["purpose"]) for p in projects[:4]] == [
        ("Metallic-RC", "Our own Rec Room"), ("Metallic-MC", "Minecraft"),
        ("Metallic-RB", "Roblox Rec Room"), ("Metallic-PX", "Progress")]
    assert len({p["repository_id"] for p in projects}) == 6
    assert project_for_repository(1420186760)["name"] == "Metallic-RC"
    assert project_for_repository(1) is None


def test_catalog_does_not_invent_live_domain_or_repository_access():
    catalog = project_catalog()
    assert catalog["domain"] == {"name": "metallic.club", "owner_reported_purchased": True,
                                  "dns_verified": False, "deployment_verified": False}
    assert not catalog["grants_permissions"]
    catalog["projects"][0]["name"] = "corrupted"
    assert project_catalog()["projects"][0]["name"] == "Metallic-RC"


def test_cli_catalog_works_without_github_credentials(capsys, monkeypatch):
    from argparse import Namespace
    from star.cli import main

    monkeypatch.delenv("STAR_GITHUB_READ_TOKEN", raising=False)
    asyncio.run(main(Namespace(command="project-catalog")))
    result = json.loads(capsys.readouterr().out)
    assert result["projects"][3]["name"] == "Metallic-PX"


def test_mcp_exposes_only_read_only_tools_and_a_bounded_inventory():
    from star.github_inventory_mcp import build_server

    class Reader:
        async def inventory(self):
            return {"complete": True, "repository_count": 30, "repositories": [
                {"repository_id": i, "full_name": f"owner/repo{i}", "visibility": "private",
                 "default_branch": "main", "reported_permissions": {}, "project": None} for i in range(30)]}

    server = build_server(Reader)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "metallic_project_names", "github_repository_inventory", "github_repository_resolve", "github_repository_read"}
    assert all(tool.annotations.readOnlyHint and not tool.annotations.destructiveHint for tool in tools)
    result = asyncio.run(server.call_tool("github_repository_inventory", {"offset": 0, "limit": 25}))
    # FastMCP returns both text blocks and structured output for dictionary annotations.
    structured = result[1] if isinstance(result, tuple) else json.loads(result[0].text)
    assert structured["returned_count"] == 25 and structured["remaining_count"] == 5
    assert structured["next_offset"] == 25
