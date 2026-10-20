"""Exercise the actual STAR Settings and curated gateway, with no real credential or network."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from jsonschema.exceptions import ValidationError

from star.desktop_core import Settings, needs_project_tools
from star.github_inventory import GitHubInventoryReader
from star.github_repository_tools import RepositoryTools, REPOSITORY_TOOL_NAMES
from star.mcp_connections import GitHubRepositoryConnector, MCPGateway, Server, check_destination, presets


def settings(enabled=True, source="gh"):
    return SimpleNamespace(mcp_github_repositories=enabled, github_repository_credential_source=source)


def test_settings_default_off_and_explicit_credential_choice():
    cfg = Settings()
    cfg.validate()
    assert cfg.mcp_github_repositories is False and cfg.github_repository_credential_source == "gh"
    assert "github_repositories" not in {item.name for item in presets(cfg)}
    assert MCPGateway(cfg).definitions("Read my GitHub repositories") == []
    cfg.mcp_github_repositories = True
    cfg.validate()
    assert "github_repositories" in {item.name for item in presets(cfg)}


@pytest.mark.parametrize("source", ["shell", "oauth", "", [], {}, True])
def test_invalid_credential_source_is_refused_by_settings_and_gateway(source):
    cfg = Settings(github_repository_credential_source=source)
    with pytest.raises(ValueError):
        cfg.validate()
    with pytest.raises(ValueError):
        MCPGateway(settings(source=source))


@pytest.mark.parametrize("enabled", ["true", 1, None, []])
def test_truthy_values_are_not_new_github_grants(enabled):
    cfg = Settings(mcp_github_repositories=enabled)
    with pytest.raises(ValueError):
        cfg.validate()
    assert "github_repositories" not in {item.name for item in presets(settings(enabled=enabled))}


def test_project_routing_only_adds_github_tools_when_switch_is_enabled():
    assert not needs_project_tools("Which of my GitHubs can you access?")
    assert needs_project_tools("Which of my GitHubs can you access?", github_repositories=True)
    assert needs_project_tools("What is Metallic-PX?", github_repositories=True)
    assert not needs_project_tools("Hello", github_repositories=True)


def test_desktop_settings_bridge_saves_the_explicit_reader_choice_without_credentials(tmp_path):
    from star.react_shell import apply_setting_changes

    cfg = Settings()
    apply_setting_changes(cfg, {"mcp_github_repositories": True,
                               "github_repository_credential_source": "env",
                               "STAR_GITHUB_READ_TOKEN": "must-not-be-persisted"})
    path = tmp_path / "settings.json"
    cfg.save(path)
    restored = Settings.load(path)
    assert restored.mcp_github_repositories is True
    assert restored.github_repository_credential_source == "env"
    assert "must-not-be-persisted" not in path.read_text()
    apply_setting_changes(restored, {"github_repository_credential_source": "unapproved"})
    with pytest.raises(ValueError):
        restored.save(path)
    assert Settings.load(path).github_repository_credential_source == "env"


def test_gateway_discovery_precedes_calls_and_does_not_lookup_credentials(monkeypatch):
    import star.github_repository_tools as tools_module

    def forbidden(**kwargs):
        raise AssertionError("Discovery must not ask for a credential")

    monkeypatch.setattr(tools_module, "from_env", forbidden)

    async def run():
        gateway = MCPGateway(settings())
        with pytest.raises(PermissionError, match="search"):
            await gateway.call("star_mcp_call", {"server": "github_repositories", "tool": "metallic_project_names", "arguments": {}})
        result = await gateway.search("github metallic", limit=6)
        assert {item["tool"] for item in result["tools"]} == REPOSITORY_TOOL_NAMES
        catalog = await gateway.call("star_mcp_call", {"server": "github_repositories", "tool": "metallic_project_names", "arguments": {}})
        decoded = json.loads(catalog["result"]["output"])
        assert decoded["projects"][0]["name"] == "Metallic-RC"
        assert catalog["result"]["untrusted"] and not decoded["grants_permissions"]
        with pytest.raises(ValidationError):
            await gateway.call("star_mcp_call", {"server": "github_repositories", "tool": "metallic_project_names", "arguments": {"run": "anything"}})

    asyncio.run(run())


def test_existing_http_destination_gate_still_refuses_internal_or_arbitrary_urls():
    server = presets(settings())[0]
    with pytest.raises(PermissionError):
        check_destination(server)
    for url in ("https://api.github.com", "http://127.0.0.1:9999/mcp", "internal:other"):
        with pytest.raises(PermissionError):
            GitHubRepositoryConnector(Server("github_repositories", "test", url, "internal-v1", REPOSITORY_TOOL_NAMES, credential_source="gh"))


def test_actual_gateway_invokes_bounded_reader_with_injected_transport(monkeypatch):
    import star.github_repository_tools as tools_module

    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[{"id": 1420186760, "node_id": "R_fixture", "full_name": "owner/AfterRename",
                                        "private": True, "permissions": {"pull": True, "push": False}, "default_branch": "main"}])

    monkeypatch.setattr(tools_module, "from_env", lambda **kwargs: GitHubInventoryReader("fixture", transport=httpx.MockTransport(handle)))

    async def run():
        gateway = MCPGateway(settings())
        await gateway.search("github inventory")
        result = await gateway.call("star_mcp_call", {"server": "github_repositories", "tool": "github_repository_inventory", "arguments": {}})
        data = json.loads(result["result"]["output"])
        assert data["complete"] and data["repository_count"] == 1
        assert data["repositories"][0]["full_name"] == "owner/AfterRename"
        assert data["repositories"][0]["project_name"] == "Metallic-RC"
        assert data["repositories"][0]["reported_permissions"]["push"] is False
        probe = await gateway.probe("github_repositories")
        assert probe["connected"] and probe["repository_count"] == 1 and probe["complete"]
        assert probe["scope"] == "repositories_visible_to_this_credential"
    asyncio.run(run())
    assert len(calls) == 2 and all(call.method == "GET" for call in calls)


def test_connection_probe_refuses_partial_inventory(monkeypatch):
    import star.github_repository_tools as tools_module
    class Reader:
        async def inventory(self):
            return {"repositories": [], "repository_count": 0, "complete": False}
    monkeypatch.setattr(tools_module, "from_env", lambda **kwargs: Reader())
    with pytest.raises(RuntimeError, match="incomplete"):
        asyncio.run(MCPGateway(settings()).probe("github_repositories"))


def test_tool_output_remains_valid_json_under_gateway_budget():
    class Reader:
        async def read(self, *args, **kwargs):
            return {"content": "\u0000" * 7000, "truncated": False, "read_only": True}

    data = asyncio.run(RepositoryTools(reader_factory=Reader).call("github_repository_read", {"repository_id": 1, "path": "README.md"}))
    encoded = json.dumps(data, ensure_ascii=False)
    assert len(encoded) <= 11000 and json.loads(encoded)["truncated"] is True


def test_tool_inventory_omissions_remain_consistent_under_output_budget():
    class Reader:
        async def inventory(self):
            return {"repositories": [{"repository_id": i, "full_name": "owner/" + "r" * 240,
                                       "visibility": "private", "default_branch": "b" * 255,
                                       "reported_permissions": {}, "project": None} for i in range(25)], "repository_count": 25}

    data = asyncio.run(RepositoryTools(reader_factory=Reader).call("github_repository_inventory", {}))
    assert len(json.dumps(data, ensure_ascii=False)) <= 11000
    assert data["returned_count"] == len(data["repositories"]) < 25
    assert data["returned_count"] + data["remaining_count"] == 25
    assert data["next_offset"] == data["returned_count"]
