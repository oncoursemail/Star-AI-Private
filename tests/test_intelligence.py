"""Offline intelligence integration tests: no network, GPU, Obsidian plugin or Graphify CLI required."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from star.agent import execute
from star.agent_skills import SkillLibrary, install_starters
from star.desktop_core import Settings
from star.graphify_bridge import GraphifyGraph
from star.intelligence import LocalIntelligence, for_settings
from star.obsidian_bridge import ObsidianVault


def test_skill_starters_discovered_and_read_only(tmp_path):
    home = tmp_path / "app"
    install_starters(home / "skills")
    library = SkillLibrary(workspace=None, home=home)
    names = {row["name"] for row in library.list()["skills"]}
    assert {"roblox-ui-craft", "roblox-luau-review", "evidence-first-debugging"} <= names
    details = library.load("roblox-ui-craft")
    assert "viewport sizes" in details["instructions"]
    assert "no additional permissions" in details["notice"].lower()
    original = home / "skills" / "roblox-ui-craft" / "SKILL.md"
    original.write_text(original.read_text() + "\nUSER CHANGE\n", encoding="utf-8")
    install_starters(home / "skills")
    assert "USER CHANGE" in original.read_text()


def test_skill_references_and_path_escape_rejected(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    folder = project / ".agents" / "skills" / "sample-skill"
    refs = folder / "references"
    refs.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: sample-skill\ndescription: Safe local guide\n---\n# Sample\nRead refs.\n")
    (refs / "guide.md").write_text("Source documentation only", encoding="utf-8")
    (project / "secret.md").write_text("Do not read", encoding="utf-8")
    library = SkillLibrary(workspace=project, home=home)
    assert library.load("sample-skill")["references"] == ["references/guide.md"]
    assert "Source" in library.read_reference("sample-skill", "references/guide.md")["content"]
    for path in ("../../secret.md", "references/../../../secret.md", "scripts/run.py", ".hidden.md"):
        with pytest.raises((ValueError, PermissionError)):
            library.read_reference("sample-skill", path)


def test_skill_invalid_yaml_and_duplicates_are_not_loaded(tmp_path):
    home = tmp_path / "home"
    roots = [tmp_path / "workspace" / ".agents" / "skills", home / "skills"]
    for root in roots:
        folder = root / "valid-skill"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: valid-skill\ndescription: Valid human-readable workflow\n---\nRead only\n")
    bad = roots[0] / "bad-name"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: other-name\ndescription: Invalid mismatch\n---\nNo\n")
    library = SkillLibrary(workspace=tmp_path / "workspace", home=home)
    skills = library.catalog()
    assert len(skills) == 1
    assert skills[0].source == "project"
    assert skills[0].name == "valid-skill"


def test_obsidian_local_search_list_and_read(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("private credential")
    (vault / "VALEN.md").write_text("# VALEN\nStylized evergreen trees and rain")
    (vault / "Development").mkdir()
    (vault / "Development" / "decisions.md").write_text("Keep the gameplay server-authoritative.")
    obs = ObsidianVault(vault)
    entries = obs.list()["notes"]
    assert "VALEN.md" in entries
    assert "Development/decisions.md" in entries
    assert not any(".obsidian" in p for p in entries)
    hit = obs.search("evergreen trees")
    assert hit["notes"][0]["path"] == "VALEN.md"
    assert "evergreen" in obs.read("VALEN.md")["content"]
    page = obs.read("VALEN.md", start_line=2, max_lines=1)
    assert page["total_lines"] == 2 and page["end_line"] == 2
    assert "evergreen" in page["content"]
    with pytest.raises(ValueError):
        obs.read("VALEN.md", start_line=3)
    with pytest.raises(PermissionError):
        obs.read(".obsidian/config.md")
    with pytest.raises(PermissionError):
        obs.read("../outside.md")
    with pytest.raises(PermissionError):
        obs.read("Development/../VALEN.md")


def _graph(tmp_path: Path):
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir(exist_ok=True)
    data = {
        "directed": True,
        "graph": {"schema_version": "test-1", "graphify_version": "fixture"},
        "nodes": [
            {"id": "n1", "label": "Inventory UI", "source_file": "frontend/inventory.tsx"},
            {"id": "n2", "label": "Inventory Server", "source_file": "server/inventory.luau"},
            {"id": "n3", "label": "DataStore", "source_file": "server/store.luau"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "relation": "CALLS", "confidence": "EXTRACTED", "source_file": "frontend/inventory.tsx"},
            {"source": "n2", "target": "n3", "relation": "WRITES", "confidence": "INFERRED", "source_file": "server/inventory.luau"},
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data))
    return GraphifyGraph(tmp_path)


def test_graphify_local_relationships_and_provenance(tmp_path):
    graph = _graph(tmp_path)
    assert graph.available()
    assert graph.stats()["nodes"] == 3
    assert graph.stats()["edges"] == 2
    found = graph.query("Inventory UI")
    assert found["matches"][0]["node"]["label"] == "Inventory UI"
    assert found["matches"][0]["connections"][0]["confidence"] == "EXTRACTED"
    details = graph.explain("Inventory Server")
    assert details["found"] and details["degree"] == 2
    route = graph.path_between("Inventory UI", "DataStore")
    assert route["found"] and route["hops"] == 2
    assert route["path"][1]["via"]["relation"] == "CALLS"
    assert route["path"][2]["via"]["confidence"] == "INFERRED"
    assert not graph.path_between("non-existent concept", "Inventory UI")["found"]


def test_graphify_prefers_the_symbol_over_a_sentence_that_mentions_it(tmp_path):
    """Real Graphify output labels a function "name()" and also emits docstring nodes.

    Asking about run_task must resolve to the function, not to a test docstring that mentions it.
    """
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    data = {
        "directed": False,
        "nodes": [
            {"id": "doc1", "label": "A private app-data folder and a fake model client behind run_task.",
             "source_file": "tests/test_first_token.py"},
            {"id": "fn1", "label": "run_task()", "source_file": "star/desktop_core.py"},
            {"id": "m1", "label": ".connection_for()", "source_file": "star/providers.py"},
        ],
        "links": [
            {"source": "fn1", "target": "m1", "relation": "calls", "confidence": "EXTRACTED",
             "source_file": "star/desktop_core.py"},
            {"source": "doc1", "target": "fn1", "relation": "rationale_for", "confidence": "EXTRACTED",
             "source_file": "tests/test_first_token.py"},
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data))
    graph = GraphifyGraph(tmp_path)
    assert graph.explain("run_task")["node"]["label"] == "run_task()"
    assert graph.explain("run_task()")["node"]["label"] == "run_task()"
    assert graph.explain("connection_for")["node"]["label"] == ".connection_for()"
    route = graph.path_between("run_task", "connection_for")
    assert route["found"] and route["hops"] == 1


def test_graphify_missing_invalid_and_escape(tmp_path):
    graph = GraphifyGraph(tmp_path)
    assert not graph.available()
    with pytest.raises(FileNotFoundError):
        graph.stats()
    root = tmp_path / "graphify-out"
    root.mkdir()
    (root / "graph.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        graph.query("test")


def test_hub_only_offers_relevant_tools_and_enforces_entitlements(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "notes.md").write_text("Obsidian answer", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _graph(workspace)
    home = tmp_path / "user-profile"
    hub = LocalIntelligence(home=home, workspace=workspace, obsidian_vault=vault)
    status = hub.status()
    assert status["skills"]["count"] >= 3
    assert status["graphify"]["export_detected"]
    assert status["obsidian"]["enabled"]
    assert hub.definitions("How are you?") == []
    skill_names = {tool["name"] for tool in hub.definitions("Build a Roblox UI")}
    assert "star_skill_load" in skill_names
    vault_names = {tool["name"] for tool in hub.definitions("Search my Obsidian notes")}
    assert "star_obsidian_search" in vault_names
    graph_tools = hub.definitions("Trace a graph dependency")
    assert "star_graphify_path" in {tool["name"] for tool in graph_tools}
    with pytest.raises(PermissionError):
        hub.call("star_obsidian_read", {"path": "notes.md"}, enabled=set())
    with pytest.raises(Exception):
        hub.call("star_obsidian_search", {"query": ""}, enabled={"star_obsidian_search"})
    result = hub.call("star_obsidian_read", {"path": "notes.md"}, enabled={"star_obsidian_read"})
    assert result["content"] == "Obsidian answer"


def test_desktop_settings_are_opt_in_and_json_persistent(tmp_path):
    file = tmp_path / "settings.json"
    settings = Settings()
    assert not settings.obsidian_enabled
    assert settings.skills_enabled
    assert settings.graphify_enabled
    settings.validate()
    settings.obsidian_enabled = True
    with pytest.raises(ValueError):
        settings.validate()
    vault = tmp_path / "vault"
    vault.mkdir()
    settings.obsidian_vault = str(vault)
    settings.save(file)
    fresh = Settings.load(file)
    assert fresh.obsidian_enabled and fresh.obsidian_vault == str(vault)
    hub = for_settings(fresh, tmp_path / "data")
    assert hub.status()["obsidian"]["read_only"] is True


def test_agent_dispatches_authorized_intelligence_without_studio(tmp_path):
    class Answers:
        def __init__(self):
            self.calls = []
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                message = SimpleNamespace(content="", tool_calls=[
                    SimpleNamespace(id="one", function=SimpleNamespace(
                        name="star_skill_catalog", arguments="{}"))])
            else:
                message = SimpleNamespace(content="I checked the available local skills.", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    async def run():
        answer_model = Answers()
        client = SimpleNamespace(chat=SimpleNamespace(completions=answer_model))
        hub = LocalIntelligence(home=tmp_path / "data")
        answer, messages, _ = await execute(client=client, model="local",
            prompt="What Roblox skills can you use?", image_paths=[], intelligence=hub,
            context_chars=40000)   # the bundled catalogue (~120 skills) outgrew the 25k default
        assert "skills" in answer.lower()
        assert any(m["role"] == "tool" and "roblox-ui-craft" in m["content"] for m in messages)
        assert [m["role"] for m in messages].count("system") == 1
        assert "star_skill_catalog" in [t["function"]["name"]
            for t in answer_model.calls[0]["tools"]]
    asyncio.run(run())
