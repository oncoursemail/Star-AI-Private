"""The tool catalogue STAR offers the model in Agent mode, through the app's own `run_task`.

Why this file exists: the real-window acceptance run asks the model, in Agent mode, to call
`star_skill_catalog`. When that step fails, the first question is whether STAR offered the tool at
all. These tests answer it offline: they run `desktop_core.run_task` (the function the window
calls) against a scripted fake model and read the `tools` field of the request it built.

The expected names are written out, one list per source, so a tool that stops being offered (or a
new one that appears) fails a test here and has to be changed on purpose. The lists were produced by
running these same scenarios against the settings-ui branch at a7a36a3 (integration round 4 plus
Settings); every name offered there is still offered, and round 5 added the three workspace_game tools.
Roblox Studio tools are not built in: they come from the connected Studio server's own catalogue and
pass star/policy.py (covered in tests/test_policy.py and tests/test_policy_schema_security.py).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import star.desktop_core as core
from star import providers, server_roles, turn_memory
from star.desktop_core import Conversations, Settings, run_task

LAN = "http://192.168.1.20:8080/v1"          # documentation placeholder, not a real machine (star:allow)
KEY = "test-server-key-0123456789"           # synthetic (star:allow)
# The prompt of the acceptance step (scripts/shell_acceptance.py, PROMPT_AGENT).
ACCEPTANCE_PROMPT = ("Call the star_skill_catalog tool once, then tell me in one short sentence "
                     "how many Agent Skills it returned.")

# Attached to every Agent-mode request (star/agent.py).
ALWAYS = ["star_delegate"]
# Agent Skills (star/intelligence.py SKILL_TOOLS): on by default (Settings.skills_enabled).
SKILLS = ["star_skill_catalog", "star_skill_load", "star_skill_reference"]
# The owner's Obsidian vault, read-only (OBSIDIAN_TOOLS): Settings.obsidian_enabled and a vault folder.
OBSIDIAN = ["star_obsidian_search", "star_obsidian_read", "star_obsidian_list", "star_obsidian_links"]
# The workspace's Graphify graph (GRAPHIFY_TOOLS): a workspace with graphify-out/graph.json.
GRAPHIFY = ["star_graphify_query", "star_graphify_explain", "star_graphify_path", "star_graphify_stats"]
# Public Roblox research (ROBLOX_GAME_TOOLS, ROBLOX_KNOWLEDGE_TOOLS, ROBLOX_VIDEO_TOOLS).
ROBLOX_GAMES = ["star_roblox_resolve_game_url", "star_roblox_resolve_place", "star_roblox_search_games",
                "star_roblox_game_report", "star_roblox_compare_games", "star_roblox_game_image"]
ROBLOX_LINKS = ["star_roblox_docs", "star_roblox_docs_read"]      # only without STAR Knowledge
ROBLOX_FORUM = ["star_roblox_forum_search", "star_roblox_forum_topic", "star_roblox_forum_latest"]
ROBLOX_VIDEO = ["star_roblox_youtube_search", "star_roblox_youtube_video"]
# STAR Knowledge (DOC_KNOWLEDGE_TOOLS): the indexed documentation, when the service is configured.
STAR_KNOWLEDGE = ["star_docs_search", "star_api_lookup", "star_luau_check"]
# Roblox Open Cloud with the owner's key (ROBLOX_CLOUD_TOOLS).
ROBLOX_CLOUD = ["star_roblox_cloud_universe", "star_roblox_cloud_status", "star_roblox_cloud_place",
                "star_roblox_cloud_data_stores", "star_roblox_cloud_action", "star_roblox_cloud_request_publish",
                "star_roblox_cloud_request_test"]
# Prompt-scoped Roblox Intelligence Hub tools (ROBLOX_HUB_TOOLS); catalog words, and analytics only with an owner allowlist.
HUB = ["star_roblox_marketplace_search", "star_roblox_creator_store_search", "star_roblox_creator_asset",
       "star_roblox_analytics_metrics", "star_roblox_analytics_poll", "star_roblox_gameplay_telemetry_plan"]
# Prompt-scoped craft tools; not part of the ordered general-prompt lists below.
CRAFT = ["star_roblox_craft_audit", "star_roblox_craft_recipe"]
# Experimental Asset Forge (star/intelligence.py ASSET_TOOLS); owner opt-in required.
ASSET = ["star_asset_search", "star_building_plan", "star_terrain_preview"]
# Business tools (star/commerce_tools.py); owner opt-in (commerce_enabled), prompt-scoped, propose-only.
COMMERCE = ["star_commerce_overview", "star_commerce_draft_candidate", "star_commerce_propose_action"]
# Optional architectural planning tools; STAR_ARCHITECTURE_TOOLS=1 only.
ARCHITECTURE = ["star_architecture_preview", "star_architecture_compare_styles"]
# Prepared shared stores only: not in ordered general-prompt tool expectations.
SHARED_BRAIN = ["shared_brain_query", "shared_brain_stats"]
# Prompt-scoped design and map-plan tools, and the opt-in live Roblox docs (off unless enabled); not part
# of the ordered general-prompt lists below (tests/test_design_roblox_tools.py covers their gating; the opt-in
# Studio lab tool: tests/test_studio_lab.py).
DESIGN_MAPS = ["star_design_search", "star_design_md", "star_roblox_map_plan", "star_roblox_studio_lab",
               "star_roblox_docs_live_search", "star_roblox_docs_live_page", "star_roblox_vfx_make"]
# The workspace folder (star/workspace.py TOOLS); workspace_write only with Settings.workspace_edit.
WORKSPACE_READ = ["workspace_list", "workspace_read", "workspace_search"]
WORKSPACE_WRITE = ["workspace_write", "workspace_edit"]
# Three additional read-only Creator Intelligence tools, in their actual registration order.
WORKSPACE_CREATOR = ["workspace_binary_triage", "workspace_asset_audit", "workspace_game_graph"]
# Game project tools plus the deliberately read-only Starry Eye evidence and design diversity checks.
WORKSPACE_GAME = ["workspace_game_discover", "workspace_game_inspect", "workspace_game_plan",
                  "workspace_starry_eye_audit", "workspace_game_concept_rank"]
# Read-only MCP connections (star/mcp_connections.py TOOLS): when one is switched on in Settings.
MCP = ["star_mcp_search", "star_mcp_call"]
# Public MCP Registry search (star/mcp_registry.py TOOLS): Agent mode with "Search the web" on, and a prompt
# that names MCP. It reads metadata only and connects nothing.
REGISTRY = ["star_mcp_registry_search"]
# Tool Workshop (star/tool_workshop.py TOOL_SCHEMAS).
WORKSHOP = ["star_toolforge_list", "star_toolforge_propose", "star_toolforge_test", "star_toolforge_run"]
# The research team (star/specialist_agents.py DELEGATE_TOOL).
SPECIALISTS = ["star_delegate_research"]
CALCULATOR = ["star_calculate"]
# Composer switches: research (web search) and the STAR source reader.
WEB = ["star_web_search", "star_web_fetch"]   # star_web_fetch (star/web_fetch.py) comes with search
GITHUB = ["star_github_tree", "star_github_read"]


def reply(content=None, calls=None):
    return SimpleNamespace(model="star-fast", choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls))])


def tool_call(name, arguments="{}"):
    return SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=arguments))


class Models:
    def __init__(self):
        self.responses, self.requests = [], []

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.responses.pop(0) if self.responses else reply("done")


class Client:
    def __init__(self, models):
        self.chat = SimpleNamespace(completions=models)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def forget_process_memory():
    """What earlier tests in this process learned about a server (models, limits, slots, sticky tools)."""
    server_roles.forget()
    turn_memory.forget()
    providers._SERVER_LIMITS.clear()
    providers._MODEL_NAMES.clear()
    providers._SLOT_TABLE.clear()


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A private app-data folder and a fake model behind run_task, as the window would call it."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    monkeypatch.delenv("STAR_ROBLOX_READ_API_KEY", raising=False)
    forget_process_memory()
    models = Models()
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    home = core.app_data()
    home.mkdir(parents=True, exist_ok=True)
    events = []

    def turn(prompt, *, settings=None, answers=(), **options):
        settings = settings or Settings(provider="star_server", server_endpoint=LAN, model="star-fast",
                                        knowledge_endpoint="off")
        chats = Conversations(home / "conversations.sqlite3")
        try:
            chat = chats.new_chat(settings.project)
            chats.add(settings.project, "user", prompt, chat_id=chat)
        finally:
            chats.close()
        models.responses.extend(answers)
        first = len(models.requests)
        answer = run_task(settings, prompt, chat_id=chat, on_event=events.append, mode="agent", **options)
        return SimpleNamespace(answer=answer, requests=models.requests[first:])

    yield SimpleNamespace(turn=turn, events=events, home=home, tmp=tmp_path)
    forget_process_memory()


def offered(request) -> list[str]:
    return [tool["function"]["name"] for tool in request.get("tools") or []]


def test_the_acceptance_prompt_is_offered_the_agent_skills_catalogue(desk):
    """Default settings, a new chat, Agent mode: exactly the delegate tool and the three skill tools."""
    result = desk.turn(ACCEPTANCE_PROMPT)
    assert offered(result.requests[0]) == ALWAYS + SKILLS
    assert result.requests[0]["tool_choice"] == "auto"
    chosen = [event for event in desk.events if event.get("event") == "route_selected"]
    assert [event["profile"] for event in chosen] == ["agent"]


def test_a_scripted_model_calls_the_skill_catalogue_and_gets_the_real_list(desk):
    """The whole loop: the model asks for star_skill_catalog, STAR runs it, the result goes back."""
    result = desk.turn(ACCEPTANCE_PROMPT, answers=[
        reply(None, [tool_call("star_skill_catalog")]),
        reply("The star_skill_catalog tool returned the Agent Skills."),
    ])
    assert result.answer == "The star_skill_catalog tool returned the Agent Skills."
    assert len(result.requests) == 2
    assert {"event": "tool_started", "tool": "star_skill_catalog"} in desk.events
    assert {"event": "tool_finished", "tool": "star_skill_catalog", "is_error": False} in desk.events
    # The second request carries the tool's own output: the installed skills, by name.
    sent_back = [message for message in result.requests[1]["messages"] if message["role"] == "tool"]
    assert len(sent_back) == 1
    payload = json.loads(sent_back[0]["content"])
    assert payload["isError"] is False
    skills = json.loads(payload["output"])["skills"]
    names = {skill["name"] for skill in skills}
    assert {"roblox-ui-craft", "roblox-luau-review", "evidence-first-debugging"} <= names
    assert len(skills) >= 12
    # The tools stay attached on the follow-up call, in the same order.
    assert offered(result.requests[1]) == ALWAYS + SKILLS


EVERYTHING_PROMPT = (
     "Calculate 2 + 2, then research this Roblox game and its players for my notes: search the devforum, watch the YouTube "
    "video tutorial, read the docs, check the Open Cloud data store, look at the graph of the codebase, "
    "list the MCP connector tool catalog, build a custom tool, and delegate to the research team.")


def everything_settings(desk, **fields) -> Settings:
    workspace = desk.tmp / "workspace"
    (workspace / "graphify-out").mkdir(parents=True, exist_ok=True)
    (workspace / "graphify-out" / "graph.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
    vault = desk.tmp / "vault"
    vault.mkdir(exist_ok=True)
    return Settings(**{"provider": "star_server", "server_endpoint": LAN, "model": "star-fast",
                       "knowledge_endpoint": "off", "workspace": str(workspace), "obsidian_enabled": True,
                       "obsidian_vault": str(vault), "mcp_graphify_docs": True, **fields})


def everything_on(desk, monkeypatch, *, knowledge: bool, **fields):
    """Every built-in source switched on, with nothing leaving the test process."""
    import star.intelligence as intelligence
    import star.roblox_cloud as roblox_cloud
    import star.web_search as web_search

    assert intelligence._VAULT_TRIGGER.search(EVERYTHING_PROMPT)

    async def no_search(*_args, **_kwargs):
        return []
    monkeypatch.setattr(web_search, "search_web", no_search)
    monkeypatch.setattr(roblox_cloud.RobloxCloud, "status", lambda self: {"key_present": True})
    if knowledge:   # a configured STAR Knowledge service (only its presence matters for the catalogue)
        monkeypatch.setattr(intelligence, "client_for", lambda settings: SimpleNamespace(configured=True))
    result = desk.turn(EVERYTHING_PROMPT, settings=everything_settings(desk, **fields),
                       research=True, github_enabled=True)
    return offered(result.requests[0])


def test_every_built_in_tool_is_offered_when_its_source_is_on(desk, monkeypatch):
    # Every source on is more tool text than the default 26,000-character request budget (the web
    # page reader, star_web_fetch, tipped it over); this test is about which tools are offered.
    names = everything_on(desk, monkeypatch, knowledge=False, context_chars=40000)
    expected = (CALCULATOR + GITHUB + ALWAYS + WEB + WORKSPACE_READ + WORKSPACE_CREATOR + WORKSPACE_GAME + SKILLS + OBSIDIAN + GRAPHIFY
                + ROBLOX_GAMES + ROBLOX_LINKS + ROBLOX_FORUM + ROBLOX_VIDEO + ROBLOX_CLOUD + MCP + REGISTRY + WORKSHOP
                + SPECIALISTS)
    assert names == expected          # the order is part of the request the server caches
    assert len(names) == len(set(names))


def test_star_knowledge_replaces_the_link_finder_and_write_needs_the_edit_switch(desk, monkeypatch):
    # Every source on plus the calculator is more tool text than the default 26,000-character request budget;
    # this test is about which tools are offered, not about the budget, so give it room.
    names = everything_on(desk, monkeypatch, knowledge=True, workspace_edit=True, context_chars=40000)
    expected = (CALCULATOR + GITHUB + ALWAYS + WEB + WORKSPACE_READ + WORKSPACE_WRITE + WORKSPACE_CREATOR + WORKSPACE_GAME + SKILLS + OBSIDIAN
                + GRAPHIFY + STAR_KNOWLEDGE + ROBLOX_GAMES + ROBLOX_FORUM + ROBLOX_VIDEO + ROBLOX_CLOUD + MCP
                + REGISTRY + WORKSHOP + SPECIALISTS)
    assert names == expected
    assert not set(ROBLOX_LINKS) & set(names)


def test_switching_agent_skills_off_removes_only_the_skill_tools(desk):
    settings = Settings(provider="star_server", server_endpoint=LAN, model="star-fast",
                        knowledge_endpoint="off", skills_enabled=False)
    result = desk.turn(ACCEPTANCE_PROMPT, settings=settings)
    assert offered(result.requests[0]) == ALWAYS


def test_the_written_lists_are_the_whole_built_in_catalogue():
    """A built-in tool added to (or dropped from) a source table must be added to the lists above."""
    from star import intelligence, mcp_connections, mcp_registry, specialist_agents, tool_workshop, workspace
    assert set(intelligence.ALL_TOOLS) == set(SKILLS + OBSIDIAN + GRAPHIFY + ROBLOX_GAMES + ROBLOX_LINKS
                                             + ROBLOX_FORUM + ROBLOX_VIDEO + STAR_KNOWLEDGE + ROBLOX_CLOUD
                                             + HUB + CRAFT + ASSET + SHARED_BRAIN + DESIGN_MAPS + ARCHITECTURE + COMMERCE)
    assert [tool["name"] for tool in intelligence.ROBLOX_HUB_TOOLS] == HUB
    assert [tool["name"] for tool in intelligence.ARCHITECTURE_TOOLS] == ARCHITECTURE
    assert [tool["name"] for tool in intelligence.ASSET_TOOLS] == ASSET
    assert [tool["name"] for tool in intelligence.COMMERCE_TOOLS] == COMMERCE
    assert [tool["name"] for tool in intelligence.SKILL_TOOLS] == SKILLS
    assert [tool["name"] for tool in intelligence.OBSIDIAN_TOOLS] == OBSIDIAN
    assert {tool["name"] for tool in workspace.TOOLS} == set(WORKSPACE_READ + WORKSPACE_WRITE + WORKSPACE_CREATOR + WORKSPACE_GAME)
    assert [tool["name"] for tool in mcp_connections.TOOLS] == MCP
    assert [tool["name"] for tool in mcp_registry.TOOLS] == REGISTRY
    assert [tool["name"] for tool in tool_workshop.TOOL_SCHEMAS] == WORKSHOP
    assert specialist_agents.DELEGATE_TOOL["name"] == SPECIALISTS[0]
    from star.calc import TOOL
    assert TOOL["name"] == CALCULATOR[0]


def test_the_registry_search_needs_the_search_the_web_switch(desk):
    """Without "Search the web" the registry tool is not offered, whatever the prompt says."""
    result = desk.turn(EVERYTHING_PROMPT, settings=everything_settings(desk))
    assert "star_mcp_registry_search" not in offered(result.requests[0])


@pytest.mark.parametrize("term", ["backlink", "backlinks", "wikilink", "wikilinks",
                                  "wiki-link", "wiki-links", "WIKI-LINKS"])
def test_obsidian_link_prompts_offer_ordered_tools_through_run_task(desk, term):
    settings = everything_settings(desk, skills_enabled=False, roblox_research_enabled=False)
    result = desk.turn(f"Show {term}.", settings=settings)
    assert len(result.requests) == 1
    assert [name for name in offered(result.requests[0]) if name.startswith("star_obsidian_")] == OBSIDIAN


@pytest.mark.parametrize("prompt", ["Give me a link.", "Give me links.", "Show a hyperlink.",
                                    "Show hyperlinks.", "Explain backlinking.", "Explain wikilinking."])
def test_generic_links_do_not_offer_obsidian_through_run_task(desk, prompt):
    # Do not include existing vault triggers such as "docs", "notes" or "research".
    settings = everything_settings(desk, skills_enabled=False, roblox_research_enabled=False)
    result = desk.turn(prompt, settings=settings)
    assert len(result.requests) == 1
    assert not set(OBSIDIAN) & set(offered(result.requests[0]))


def test_docs_remains_a_vault_trigger_when_generic_links_are_removed(desk):
    settings = everything_settings(desk, skills_enabled=False, roblox_research_enabled=False)
    result = desk.turn("Give me links to the docs.", settings=settings)
    assert len(result.requests) == 1
    assert [name for name in offered(result.requests[0]) if name.startswith("star_obsidian_")] == OBSIDIAN


def test_link_prompt_cannot_enable_a_disabled_vault_through_run_task(desk):
    settings = everything_settings(desk, obsidian_enabled=False, skills_enabled=False,
                                   roblox_research_enabled=False)
    result = desk.turn("Show backlinks and wiki-links.", settings=settings)
    assert len(result.requests) == 1
    assert not set(OBSIDIAN) & set(offered(result.requests[0]))


def test_scripted_obsidian_links_call_returns_real_evidence_through_run_task(desk):
    settings = everything_settings(desk, skills_enabled=False, roblox_research_enabled=False)
    (desk.tmp / "vault" / "Target.md").write_text("# Target\n", encoding="utf-8")
    (desk.tmp / "vault" / "Source.md").write_text("# Source\n[[Target]]\n", encoding="utf-8")
    result = desk.turn("Show backlinks for Target.md.", settings=settings, answers=[
        reply(None, [tool_call("star_obsidian_links", json.dumps({"path": "Target.md"}))]),
        reply("The backlink comes from Source.md."),
    ])
    assert result.answer == "The backlink comes from Source.md."
    assert len(result.requests) == 2
    for request in result.requests:
        assert [name for name in offered(request) if name.startswith("star_obsidian_")] == OBSIDIAN
    assert {"event": "tool_started", "tool": "star_obsidian_links"} in desk.events
    assert {"event": "tool_finished", "tool": "star_obsidian_links", "is_error": False} in desk.events
    sent_back = [message for message in result.requests[1]["messages"] if message["role"] == "tool"]
    assert len(sent_back) == 1
    payload = json.loads(sent_back[0]["content"])
    assert payload["isError"] is False
    evidence = json.loads(payload["output"])
    assert evidence["path"] == "Target.md"
    assert evidence["backlinks"] == [{"path": "Source.md", "line": 2}]
    assert evidence["backlinks_total"] == 1
    assert evidence["partial_scan"] is False
    assert evidence["read_only"] is True


def test_calculator_runs_through_real_agent_loop(desk):
    result = desk.turn("Calculate 1/3 + 1/6", answers=[
        reply(None, [tool_call("star_calculate", '{"expression":"1/3+1/6"}')]),
        reply("The result is 1/2."),
    ])
    assert result.answer == "The result is 1/2."
    assert offered(result.requests[0]) == CALCULATOR + ALWAYS      # no skills: the prompt does not ask for them
    assert {"event": "tool_started", "tool": "star_calculate"} in desk.events
    assert {"event": "tool_finished", "tool": "star_calculate", "is_error": False} in desk.events
    sent_back = [m for m in result.requests[1]["messages"] if m["role"] == "tool"]
    assert len(sent_back) == 1
    payload = json.loads(sent_back[0]["content"])
    assert payload["isError"] is False
    assert json.loads(payload["output"]) == {"result": "1/2"}


def test_ordinary_prompts_do_not_offer_the_calculator_and_it_cannot_be_called_unoffered(desk):
    result = desk.turn("Roblox 0.9.0 shipped on 2026-10-12. What do you mean by the average player?", answers=[
        reply(None, [tool_call("star_calculate", '{"expression":"1+1"}')]),
        reply("Understood."),
    ])
    assert "star_calculate" not in offered(result.requests[0])
    sent_back = [m for m in result.requests[1]["messages"] if m["role"] == "tool"]
    assert json.loads(sent_back[0]["content"])["isError"] is True      # refused: the tool was never offered


@pytest.mark.parametrize("source,expected_rules", [
    ("--!strict\ntask.wait(1)", set()),
    ("--!strict\nwait(1)", {"luau-legacy-task"}),
])
def test_craft_audit_is_offered_and_runs_through_real_agent(desk, source, expected_rules):
    arguments = json.dumps({"instances": [], "scripts": [
        {"path": "ServerScriptService.Timer", "class": "Script", "source": source}]})
    result = desk.turn("Audit this Roblox UI source with star_roblox_craft_audit.", answers=[
        reply(None, [tool_call("star_roblox_craft_audit", arguments)]),
        reply("The craft audit finished."),
    ])
    assert set(CRAFT) <= set(offered(result.requests[0]))
    assert len(result.requests) == 2
    assert {"event": "tool_finished", "tool": "star_roblox_craft_audit", "is_error": False} in desk.events
    sent_back = [message for message in result.requests[1]["messages"] if message["role"] == "tool"]
    assert len(sent_back) == 1
    payload = json.loads(sent_back[0]["content"])
    assert payload["isError"] is False
    report = json.loads(payload["output"])
    assert report["reviewed_scripts"] == 1
    assert report["read_only"] is True and report["executed"] is False
    assert {item["rule"] for item in report["findings"]} == expected_rules


@pytest.mark.parametrize(("name", "filename", "kind"), [
    ("workspace_asset_audit", "character.gltf", "gltf"),
    ("workspace_game_graph", "godot_project", "godot"),
    ("workspace_binary_triage", "plugin.wasm", "WebAssembly"),
])
def test_creator_inspections_offered_and_dispatched_by_real_agent_turn(
        desk, name, filename, kind):
    """A scripted model reaches the actual tool offer, authorization and Workspace.call."""
    folder = desk.tmp / "creator-workspace"
    folder.mkdir()
    if kind == "gltf":
        (folder / filename).write_text('{"asset":{"version":"2.0"},"nodes":[]}',
                                       encoding="utf-8")
    elif kind == "godot":
        project = folder / filename
        project.mkdir()
        (project / "project.godot").write_text(
            '[application]\nconfig/name="Demo"\n', encoding="utf-8")
        (project / "main.tscn").write_text(
            '[node name="Root" type="Node"]\n', encoding="utf-8")
    else:
        (folder / filename).write_bytes(b"\x00asm\x01\x00\x00\x00")
    settings = Settings(provider="star_server", server_endpoint=LAN, model="star-fast",
                        knowledge_endpoint="off", workspace=str(folder),
                        workspace_edit=False, skills_enabled=False,
                        roblox_research_enabled=False)
    result = desk.turn("Inspect this selected project file.", settings=settings, answers=[
        reply(None, [tool_call(name, json.dumps({"path": filename}))]),
        reply("Inspection complete."),
    ])
    assert len(result.requests) == 2
    for request in result.requests:
        available = offered(request)
        assert [value for value in available if value in WORKSPACE_CREATOR] == WORKSPACE_CREATOR
        assert "workspace_write" not in available
    assert {"event": "tool_started", "tool": name} in desk.events
    assert {"event": "tool_finished", "tool": name, "is_error": False} in desk.events
    returned = [message for message in result.requests[1]["messages"]
                if message["role"] == "tool"]
    assert len(returned) == 1
    payload = json.loads(returned[0]["content"])
    assert payload["isError"] is False
    evidence = json.loads(payload["output"])
    assert evidence["read_only"] is True and evidence.get("executed") is not True
    assert evidence.get("format", evidence.get("engine")) == kind


@pytest.mark.parametrize("name", WORKSPACE_CREATOR)
def test_creator_inspections_reject_an_unselected_workspace_through_agent(desk, name):
    result = desk.turn("Inspect the selected artifact.", answers=[
        reply(None, [tool_call(name, '{"path":"unselected.bin"}')]),
        reply("No workspace selected."),
    ])
    assert name not in offered(result.requests[0])
    assert {"event": "tool_rejected", "tool": name} in desk.events
    assert {"event": "tool_started", "tool": name} not in desk.events
    payloads = [json.loads(message["content"]) for message in result.requests[1]["messages"]
                if message["role"] == "tool"]
    assert len(payloads) == 1 and payloads[0]["isError"] is True


def test_creator_inspections_do_not_enable_workspace_writes(desk):
    folder = desk.tmp / "readonly-workspace"
    folder.mkdir()
    settings = Settings(provider="star_server", server_endpoint=LAN, model="star-fast",
                        knowledge_endpoint="off", workspace=str(folder),
                        workspace_edit=False, skills_enabled=False)
    result = desk.turn("Inspect this workspace.", settings=settings, answers=[
        reply(None, [tool_call("workspace_write",
                              '{"path":"should-not-exist.txt","content":"unsafe"}')]),
        reply("No file created."),
    ])
    assert set(WORKSPACE_CREATOR) <= set(offered(result.requests[0]))
    assert "workspace_write" not in offered(result.requests[0])
    assert {"event": "tool_rejected", "tool": "workspace_write"} in desk.events
    assert not (folder / "should-not-exist.txt").exists()
