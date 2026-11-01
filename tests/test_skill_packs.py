"""Roblox skill packs: format, grounding files, selection, cost limits and the run_task hook."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import desktop_core, doc_grounding, skill_packs
from star.agent_skills import SkillLibrary
from star.desktop_core import Settings, run_task

NAMES = ["godot-scenes-and-nodes", "godot-gdscript-typing-and-signals", "godot-physics-and-input", "godot-ui-and-themes", "roblox-ui-layout", "roblox-secure-remotes", "roblox-datastore-safety",
         "roblox-animation-tools", "roblox-performance-streaming",
         "roblox-animation-craft", "roblox-vfx", "roblox-building-layout", "roblox-ui-styles",
         "roblox-environment-art",
         "game-obby", "game-tycoon", "game-simulator", "game-rounds",
         "game-inventory", "game-npc-quests",
         "eng-debugging", "eng-test-first", "eng-verify-before-done", "roblox-game-math",
         "design-core-loop-and-progression", "design-onboarding-and-tutorial", "design-game-feel",
         "design-level-and-obby-layout", "design-economy-and-fair-monetisation", "design-ui-ux-for-games",
         "roblox-datastore-service-patterns", "roblox-remote-event-function-patterns",
         "roblox-tweenservice-easing",
         "roblox-studio-mcp-workflow", "roblox-replication-hot-paths", "roblox-editablemesh-batching", "roblox-editable-memory-streaming",
         "roblox-asset-upload-moderation", "roblox-multi-agent-studio", "roblox-architecture-blender", "roblox-combat-hitboxes", "roblox-pathfinding-npc", "roblox-physics-constraints", "roblox-collection-tags", "roblox-input-devices", "roblox-sound-design", "roblox-luau-specs", "roblox-marketplace-purchases", "roblox-teleport-matchmaking", "roblox-open-cloud",
         "roblox-purchases-badges", "roblox-vfx-composer", "roblox-cutscenes", "roblox-secondary-motion-lab",
         "roblox-server-authority", "roblox-luau-new-solver", "roblox-data-limits-2026"]
ENGINEERING = {"eng-debugging", "eng-test-first", "eng-verify-before-done"}
CORE_SERVICE_PACKS = {"roblox-datastore-service-patterns", "roblox-remote-event-function-patterns",
                      "roblox-tweenservice-easing", "roblox-purchases-badges"}
# Typed gameplay and platform packs; their grounding is checked in test_roblox_gameplay_skill_packs.py.
GAMEPLAY_PACKS = {"roblox-combat-hitboxes", "roblox-pathfinding-npc", "roblox-physics-constraints",
                  "roblox-collection-tags", "roblox-input-devices", "roblox-sound-design", "roblox-luau-specs",
                  "roblox-marketplace-purchases", "roblox-teleport-matchmaking", "roblox-open-cloud"}
UI_PROMPT = "In my Roblox game: write a LocalScript that builds a ScreenGui with a ScrollingFrame and a UIListLayout."
REMOTE_PROMPT = "In my Roblox game, my RemoteEvent handler trusts the client price. Make the server validate it."
ENGINE_NAMES = set(skill_packs.ENGINE_CONTEXTS)   # other-engine packs, tested in test_engine_skill_packs.py


def test_all_packs_ship_in_the_existing_skill_format():
    packs = skill_packs.available()
    assert [p.name for p in packs if p.name not in ENGINE_NAMES] == NAMES
    for pack in packs:
        assert pack.file.parent.name == pack.name and 1 <= len(pack.description) <= 1024
        assert pack.body.startswith("# ")
        grounding = "ATTRIBUTION.md" if pack.name in ENGINEERING else "sources.md"
        assert (pack.file.parent / "references" / grounding).is_file(), pack.name


def test_each_pack_is_short_enough_not_to_slow_the_first_token():
    for pack in skill_packs.available():
        assert len(pack.body) <= skill_packs.MAX_BODY_CHARS, (pack.name, len(pack.body))
    worst = skill_packs.render(skill_packs.available()[:skill_packs.MAX_PACKS_PER_TURN])
    assert len(worst) <= skill_packs.MAX_BLOCK_CHARS


def test_implementation_packs_cite_official_documentation_and_list_the_api_names_it_checked():
    for pack in skill_packs.available():
        # Design-source grounding is exercised through SkillLibrary in test_design_skill_packs.py.
        if (pack.name in ENGINEERING or pack.name.startswith("design-") or pack.name in CORE_SERVICE_PACKS
                or pack.name in GAMEPLAY_PACKS or pack.name in ENGINE_NAMES):
            continue
        sources = (pack.file.parent / "references" / "sources.md").read_text(encoding="utf-8")
        if pack.name in skill_packs.GODOT_PACKS:
            assert sources.count("https://docs.godotengine.org/en/stable/") >= 5, pack.name
        elif pack.name == "roblox-architecture-blender":
            # Experimental pack is OFF until API lookup and independent evaluation.
            assert sources.count("https://create.roblox.com/docs/") >= 5, pack.name
            assert pack.name not in skill_packs.DEFAULT_ENABLED
            assert "API names not yet verified by STAR Knowledge /api-lookup" in sources
        elif pack.name == "roblox-editablemesh-batching":
            # Experimental 2026 batching pack (#578): official pages, OFF until API lookup and evaluation.
            assert sources.count("https://create.roblox.com/docs/") >= 4, pack.name
            assert pack.name not in skill_packs.DEFAULT_ENABLED
            assert "API names not yet verified by STAR Knowledge /api-lookup" in sources
        elif pack.name == "roblox-secondary-motion-lab":
            # Experimental pack: three Roblox pages plus the XPBD paper and SmartBone 2; OFF until evaluated.
            assert sources.count("https://create.roblox.com/docs/") >= 3, pack.name
            assert pack.name not in skill_packs.DEFAULT_ENABLED
            assert "No native Roblox profile was collected" in sources
        else:
            assert sources.count("https://create.roblox.com/docs/") >= 5, pack.name
            assert "verified with the knowledge service /api-lookup" in sources, pack.name
        assert "http://" not in sources and "10.17" not in sources


def test_packs_do_not_contain_instructions_that_reach_beyond_the_task():
    for pack in skill_packs.available():
        text = pack.body.lower()
        for forbidden in ("ignore previous", "system prompt", "api key", "http://", "https://", "execute_luau", "publish"):
            assert forbidden not in text, (pack.name, forbidden)


def test_selection_needs_a_roblox_question_that_names_the_topic():
    assert skill_packs.matching_names(UI_PROMPT, enabled=NAMES) == ["roblox-ui-layout"]
    assert skill_packs.matching_names(REMOTE_PROMPT, enabled=NAMES) == ["roblox-secure-remotes"]
    for prompt in ("How do I centre a div in my web app UI?", "What is the capital of France?", "hello",
                   "Explain the UI of a spreadsheet", "", "   "):
        assert skill_packs.select(prompt, enabled=NAMES) == [], prompt
    assert skill_packs.select(None, enabled=NAMES) == []
    assert skill_packs.select("x" * 30_000 + " Roblox ScreenGui", enabled=NAMES) == []


def test_environment_art_pack_is_opt_in_and_stays_scoped():
    assert "roblox-environment-art" not in skill_packs.DEFAULT_ENABLED
    prompt = "In Roblox Studio, build environmental storytelling with foliage and swaying trees."
    assert skill_packs.matching_names(prompt, enabled=NAMES) == ["roblox-environment-art"]
    assert skill_packs.matching_names(prompt, enabled=["roblox-vfx"]) == []
    assert skill_packs.matching_names("Design a website with swaying trees", enabled=NAMES) == []


def test_one_generic_word_is_not_enough():
    assert skill_packs.select("In my Roblox game the UI looks plain.", enabled=NAMES) == []
    assert skill_packs.select("In my Roblox game a Tool appears.", enabled=NAMES) == []


def test_only_the_best_matching_pack_is_added():
    prompt = ("In my Roblox game: RemoteEvent OnServerEvent FireServer validation, DataStore UpdateAsync BindToClose, "
              "ScreenGui UIListLayout, Animator LoadAnimation, performance StreamingEnabled.")
    picked = skill_packs.select(prompt, enabled=NAMES)
    assert len(picked) == skill_packs.MAX_PACKS_PER_TURN == 1
    assert len(skill_packs.select(prompt, enabled=NAMES, limit=3)) == 3 and skill_packs.select(prompt, enabled=NAMES, limit=3)[0] == picked[0]
    assert skill_packs.select(prompt, enabled=NAMES, limit=0) == []


def test_environment_switch(monkeypatch):
    monkeypatch.delenv(skill_packs.ENV_VAR, raising=False)
    assert skill_packs.enabled_names() == frozenset(skill_packs.DEFAULT_ENABLED) & frozenset(NAMES)
    for value, expected in (("off", set()), ("none", set()), ("0", set()), ("all", set(NAMES) | ENGINE_NAMES),
                            ("roblox-ui-layout", {"roblox-ui-layout"}),
                            ("roblox-ui-layout, roblox-secure-remotes ,nonsense", {"roblox-ui-layout", "roblox-secure-remotes"}),
                            ("nonsense", set())):
        monkeypatch.setenv(skill_packs.ENV_VAR, value)
        assert skill_packs.enabled_names() == expected, value
        assert {p.name for p in skill_packs.select(UI_PROMPT + " " + REMOTE_PROMPT)} <= expected
    monkeypatch.setenv(skill_packs.ENV_VAR, "off")
    assert skill_packs.select(UI_PROMPT) == []


def test_render_is_empty_without_packs_and_bounded():
    assert skill_packs.render([]) == ""
    long = skill_packs.Pack("x", "d", "y" * 10_000, Path("."))
    assert len(skill_packs.render([long])) <= skill_packs.MAX_BLOCK_CHARS + 1


def test_the_skill_library_lists_bundled_packs_and_a_user_copy_wins(tmp_path):
    lib = SkillLibrary(workspace=None, home=tmp_path, bundled=skill_packs.PACKS_DIR)
    by_name = {s.name: s for s in lib.catalog()}
    assert set(NAMES) <= set(by_name) and by_name["roblox-ui-layout"].source == "bundled"
    loaded = lib.load("roblox-secure-remotes")
    assert "server is authoritative" in loaded["instructions"] and "references/sources.md" in loaded["references"]
    own = tmp_path / "skills" / "roblox-ui-layout"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("---\nname: roblox-ui-layout\ndescription: mine\n---\n# mine\n", encoding="utf-8")
    assert {s.name: s for s in lib.catalog()}["roblox-ui-layout"].source == "personal"
    assert not set(NAMES) & {s.name for s in SkillLibrary(workspace=None, home=tmp_path / "elsewhere").catalog()}   # only when asked for


class FakeModel:
    def __init__(self):
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK", tool_calls=None))])


def run_turn(monkeypatch, tmp_path, prompt, mode="auto"):
    model = FakeModel()

    @asynccontextmanager
    async def fake_client(settings, **_):
        yield model

    monkeypatch.setattr(desktop_core, "app_data", lambda: tmp_path / "STAR")
    monkeypatch.setattr(desktop_core, "open_client", fake_client)
    monkeypatch.setattr(doc_grounding, "client_for", lambda settings: None)
    events = []
    run_task(Settings(model="m"), prompt, on_event=events.append, mode=mode)
    messages = model.requests[0]["messages"]
    final = messages[-1]["content"]
    text = final if isinstance(final, str) else "".join(p.get("text", "") for p in final if isinstance(p, dict))
    return messages, text, events


def test_run_task_adds_the_pack_after_the_users_words_and_never_to_the_system_message(monkeypatch, tmp_path):
    monkeypatch.setenv(skill_packs.ENV_VAR, "all")
    messages, text, events = run_turn(monkeypatch, tmp_path, UI_PROMPT)
    assert text.startswith(UI_PROMPT) and skill_packs.BLOCK_HEADING in text and "Build UI from real objects" in text
    assert "Build UI from real objects" not in messages[0]["content"]
    event = next(e for e in events if e["event"] == "skill_packs")
    assert event["names"] == ["roblox-ui-layout"] and event["chars"] > 500


def test_run_task_without_packs_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv(skill_packs.ENV_VAR, "off")
    messages, text, events = run_turn(monkeypatch, tmp_path, UI_PROMPT)
    assert skill_packs.BLOCK_HEADING not in text and not any(e["event"] == "skill_packs" for e in events)
    other_messages, other_text, other_events = run_turn(monkeypatch, tmp_path, "What is the capital of France?")
    assert skill_packs.BLOCK_HEADING not in other_text
    # the system message is identical whether or not a pack was added (the server's prompt cache depends on it)
    monkeypatch.setenv(skill_packs.ENV_VAR, "all")
    on_messages, _, _ = run_turn(monkeypatch, tmp_path, UI_PROMPT)
    assert on_messages[0] == messages[0]


def test_quick_chat_mode_never_gets_a_pack(monkeypatch, tmp_path):
    monkeypatch.setenv(skill_packs.ENV_VAR, "all")
    _, text, events = run_turn(monkeypatch, tmp_path, UI_PROMPT, mode="fast")
    assert skill_packs.BLOCK_HEADING not in text and not any(e["event"] == "skill_packs" for e in events)


def test_engineering_packs_keep_the_attribution_and_licence_of_the_two_mit_collections():
    notices = (skill_packs.PACKS_DIR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Copyright (c) 2025 Addy Osmani" in notices and "Copyright (c) 2025 Jesse Vincent" in notices
    assert notices.count("Permission is hereby granted, free of charge") == 3   # the two collections + miqdadbadjuber/anti-slop
    for name in ENGINEERING:
        text = (skill_packs.PACKS_DIR / name / "references" / "ATTRIBUTION.md").read_text(encoding="utf-8")
        assert "MIT" in text and "github.com/addyosmani/agent-skills" in text and "github.com/obra/superpowers" in text, name
        assert "THIRD_PARTY_NOTICES.md" in text


def test_the_creation_packs_are_chosen_for_their_own_topic():
    assert skill_packs.matching_names("In my Roblox game: write easing functions with anticipation and follow-through for a sword combo.",
                                      enabled=NAMES) == ["roblox-animation-craft"]
    assert skill_packs.matching_names("In my Roblox game: spawn a ParticleEmitter burst with a Beam and a Trail on hit.",
                                      enabled=NAMES) == ["roblox-vfx"]
    assert skill_packs.matching_names("In my Roblox game: snap the modular kit walls to a grid and place the model with PivotTo.",
                                      enabled=NAMES) == ["roblox-building-layout"]
    assert skill_packs.matching_names("In my Roblox game: debug this script, it errors and crashes with attempt to index nil.",
                                      enabled=NAMES) == ["eng-debugging"]
    assert skill_packs.matching_names("In my Roblox game: fix this and tell me how you verified it works.",
                                      enabled=NAMES) == ["eng-verify-before-done"]


def test_the_new_packs_are_off_until_the_gate_has_passed_them():
    assert "roblox-vfx" in skill_packs.enabled_names({skill_packs.ENV_VAR: "all"})
    assert skill_packs.enabled_names({}) == frozenset(skill_packs.DEFAULT_ENABLED) & frozenset(NAMES)

GAME_PACKS = ("game-obby", "game-tycoon", "game-simulator",
              "game-rounds", "game-inventory", "game-npc-quests")


def test_new_game_packs_are_registered_but_switched_off_pending_evaluation():
    # Keep each new pack available for opt-in testing, but never enable it by default
    # until docs/evals.md's evaluation gate has passed it.
    assert set(GAME_PACKS) <= {pack.name for pack in skill_packs.available()}
    assert set(GAME_PACKS).isdisjoint(skill_packs.DEFAULT_ENABLED)
    assert set(GAME_PACKS).isdisjoint(skill_packs.enabled_names({}))
    assert set(GAME_PACKS) <= skill_packs.enabled_names({skill_packs.ENV_VAR: "all"})
    for name in GAME_PACKS:
        assert skill_packs.enabled_names({skill_packs.ENV_VAR: name}) == {name}


@pytest.mark.parametrize(("name", "prompt"), (
    ("game-obby", "Build a Roblox obby with checkpoints and kill bricks."),
    ("game-tycoon", "Build a Roblox tycoon with droppers and collectors."),
    ("game-simulator", "Build a Roblox simulator with rebirth and leaderstats."),
    ("game-rounds", "Build a Roblox round-based game with intermission."),
    ("game-inventory", "Build a Roblox inventory with equip and backpack."),
    ("game-npc-quests", "Build Roblox NPC quests with quest dialogue."),
))
def test_new_game_pack_routing_requires_explicit_opt_in(name, prompt):
    assert skill_packs.matching_names(prompt) == [] or name not in skill_packs.matching_names(prompt)
    assert skill_packs.matching_names(prompt, enabled={name}) == [name]


@pytest.mark.parametrize(("name", "prompt"), (
    ("roblox-datastore-service-patterns",
     "In Roblox Studio, implement DataStoreService UpdateAsync with StandardRead budgets."),
    ("roblox-remote-event-function-patterns",
     "In Roblox Studio, implement RemoteFunction OnServerInvoke with per-player validation."),
    ("roblox-tweenservice-easing",
     "In Roblox Studio, implement TweenService with TweenInfo and EasingDirection."),
))
def test_run_task_delivers_service_pack_only_when_enabled(monkeypatch, tmp_path, name, prompt):
    monkeypatch.setenv(skill_packs.ENV_VAR, name)
    messages, text, events = run_turn(monkeypatch, tmp_path, prompt)
    assert text.startswith(prompt) and "## Three correct Luau examples" in text
    injected = [e for e in events if e["event"] == "skill_packs"]
    assert len(injected) == 1 and injected[0]["names"] == [name]
    assert "## Three correct Luau examples" not in messages[0]["content"]

    monkeypatch.setenv(skill_packs.ENV_VAR, "off")
    off_messages, off_text, off_events = run_turn(monkeypatch, tmp_path, prompt)
    assert skill_packs.BLOCK_HEADING not in off_text
    assert not any(e["event"] == "skill_packs" for e in off_events)
    assert messages[0] == off_messages[0]


def test_architecture_blender_skill_is_relevant_but_off_until_evaluated():
    prompt = "In my Roblox project design an architectural facade in Blender and import a glTF."
    assert skill_packs.matching_names(prompt, enabled={"roblox-architecture-blender"}) == ["roblox-architecture-blender"]
    assert "roblox-architecture-blender" not in skill_packs.matching_names(prompt)
    assert "roblox-architecture-blender" not in skill_packs.DEFAULT_ENABLED
    assert skill_packs.enabled_names({skill_packs.ENV_VAR: "roblox-architecture-blender"}) == {"roblox-architecture-blender"}


def test_architecture_guidance_documents_opt_in_and_source_only():
    # The skill is bundled for future opt-in, but it may not suggest the installed
    # application can export Blender files or that native CI proves Studio import.
    pack = next(pack for pack in skill_packs.available() if pack.name == "roblox-architecture-blender")
    assert "STAR_ARCHITECTURE_TOOLS=1" in pack.body
    assert "source checkout of STAR" in pack.body
    assert "installed app does not include" in pack.body

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs/STAR_ARCHITECTURE_BLENDER_RESEARCH.md").read_text(encoding="utf-8")
    # The v1.0 README lists it as one Opt-in row; the caveats live in the guide it links.
    assert "Architecture planning prototype and Blender building kit (source checkout only" in readme
    assert "STAR_ARCHITECTURE_TOOLS=1" in readme
    assert "docs/STAR_ARCHITECTURE_BLENDER_RESEARCH.md" in readme
    assert "omits that protected workflow" in guide
    assert "Roblox Studio never ran" in guide


@pytest.mark.parametrize(("name", "prompt"), (
    ("godot-scenes-and-nodes", "In Godot 4 how do I instantiate a PackedScene and add_child?"),
    ("godot-gdscript-typing-and-signals", "In Godot 4 GDScript how do typed signals connect?"),
    ("godot-physics-and-input", "In Godot 4 CharacterBody2D how do physics and move_and_slide work?"),
    ("godot-ui-and-themes", "In Godot 4 how do Control UI themes and anchors work?"),
))
def test_godot_packs_are_off_and_route_only_after_opt_in(name, prompt):
    assert name not in skill_packs.DEFAULT_ENABLED
    assert name not in skill_packs.enabled_names({})
    assert skill_packs.matching_names(prompt) == []
    assert skill_packs.matching_names(prompt, enabled={name}) == [name]
    assert skill_packs.matching_names("In Roblox Studio how do I build an inventory UI?", enabled={name}) == []


def test_debugging_strict_luau_pack_is_opt_in_bounded_and_source_backed(monkeypatch, tmp_path):
    from urllib.parse import urlparse
    from re import findall

    name = "eng-debugging"
    pack = next(p for p in skill_packs.available() if p.name == name)
    assert name not in skill_packs.DEFAULT_ENABLED
    assert len(pack.body) <= skill_packs.MAX_BODY_CHARS
    assert "Unknown type NPC" in pack.body and "type NPC = Model" in pack.body
    rows = findall(r"^\| (\d+) \| \x60(.+?)\x60.*?\| \x60(.+?)\x60 \| ([S\d,]+) \|$",
                   pack.body, flags=__import__("re").MULTILINE)
    assert [int(number) for number, _, _, _ in rows] == list(range(1, 13))
    assert all(wrong != correct and wrong and correct for _, wrong, correct, _ in rows)
    source_text = (pack.file.parent / "references" / "type_sources.md").read_text(encoding="utf-8")
    import re
    ids = set(re.findall(r"^- (S\d+) — ", source_text, re.MULTILINE))
    assert ids == {f"S{i}" for i in range(1, 7)}
    assert all(set(re.findall(r"S\d+", sources)) <= ids for _, _, _, sources in rows)
    links = re.findall(r"https://[^\s)]+", source_text)
    assert len(links) == 6
    assert all(urlparse(url).hostname in {"luau.org", "create.roblox.com"} for url in links)

    library = SkillLibrary(workspace=None, home=tmp_path, bundled=skill_packs.PACKS_DIR)
    loaded = library.load(name)
    assert loaded["instructions"].strip() == pack.body
    assert "references/type_sources.md" in loaded["references"]
    assert len(skill_packs.render([pack])) <= skill_packs.MAX_BLOCK_CHARS

    prompt = "In Roblox Studio debug the Unknown type NPC error in my Luau model"
    monkeypatch.delenv(skill_packs.ENV_VAR, raising=False)
    assert skill_packs.matching_names(prompt) == []
    monkeypatch.setenv(skill_packs.ENV_VAR, name)
    assert skill_packs.matching_names(prompt) == [name]
    _, actual, events = run_turn(monkeypatch, tmp_path, prompt)
    assert actual.startswith(prompt) and "Unknown type NPC" in actual
    assert any(event["event"] == "skill_packs" and event["names"] == [name] for event in events)
    assert skill_packs.matching_names("Please debug my Python CLI exception", enabled={name}) == []
    assert skill_packs.matching_names("In Roblox Studio, build an unrelated lobby", enabled={name}) == []
    monkeypatch.setenv(skill_packs.ENV_VAR, "off")
    _, actual_off, off_events = run_turn(monkeypatch, tmp_path, prompt)
    assert "Twelve paired diagnostics" not in actual_off
    assert not any(event["event"] == "skill_packs" for event in off_events)
