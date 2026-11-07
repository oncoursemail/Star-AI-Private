import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from star import studio_atlas

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "data" / "studio_atlas"
SYSTEMS = studio_atlas.load(ATLAS)

# One realistic request per system: the closest system must be the one named.
MATCHING = [
    ("profile", "Write a Roblox script that saves player data with DataStoreService, retries on failure and handles BindToClose"),
    ("remotes", "How do I validate RemoteEvent arguments and add rate limiting so exploiters cannot spam my remote?"),
    ("inventory", "Make an inventory system with stackable items and a slot capacity"),
    ("shop", "Create a shop where players buy items, with a ProcessReceipt handler for developer products"),
    ("rounds", "I need a round based game loop with an intermission, a lobby and a round timer"),
    ("wallet", "Add a coins currency system with leaderstats that shows the balance"),
    ("combat", "Write sword combat with server side hit validation and a cooldown"),
    ("quests", "Build a quest system with objectives like kill 5 zombies and a reward"),
    ("admin", "Add admin commands with permission levels, like !kick and !ban for moderators"),
    ("uikit", "Make my UI responsive with UIScale so it works on mobile, console and different screen sizes"),
]
NOT_MATCHING = [
    "Write a short poem about the sea",
    "Make a part that changes color when the player touches it",
    "Why is my tween not playing smoothly?",
    "Explain what a metatable is in Luau",
    "Add a rotating coin pickup sound effect",
]


def test_index_lists_the_ten_systems_with_files_and_sections():
    assert [s.id for s in SYSTEMS] == [m[0] for m in MATCHING]
    for system in SYSTEMS:
        readme = (ATLAS / system.readme).read_text(encoding="utf-8")
        assert all(h in readme for h in ("## API", "## Wire it", "## Pitfalls")), system.id
        assert (ATLAS / system.module).read_text(encoding="utf-8").startswith("--!strict"), system.id
        assert len(readme) < 2600


def test_index_rejects_bad_rows(tmp_path):
    (tmp_path / "a.luau").write_text("x", encoding="utf-8")
    good = {"id": "ok-one", "title": "T", "summary": "S", "tags": ["a"], "phrases": ["b"],
            "module": "a.luau", "readme": "a.luau", "test": "a.luau"}
    assert studio_atlas.parse_index(json.dumps({"version": 1, "systems": [good]}), tmp_path)[0].id == "ok-one"
    for bad in ({**good, "module": "../outside.luau"}, {**good, "id": "Bad Id"}, {**good, "tags": []},
                {**good, "test": "missing.luau"}):
        with pytest.raises(ValueError):
            studio_atlas.parse_index(json.dumps({"version": 1, "systems": [bad]}), tmp_path)
    with pytest.raises(ValueError):
        studio_atlas.parse_index(json.dumps({"version": 1, "systems": [good, good]}), tmp_path)


@pytest.mark.parametrize("system_id,request_text", MATCHING)
def test_a_matching_request_pulls_the_right_system(system_id, request_text):
    block, used = studio_atlas.select(request_text)
    assert used and used[0].id == system_id, [(s.id, studio_atlas.score(request_text, s)) for s in SYSTEMS]
    assert block.startswith(f"[studio atlas: {system_id};") and "## API" in block and "--!strict" in block
    assert len(block) <= studio_atlas.MAX_BLOCK_CHARS


@pytest.mark.parametrize("request_text", NOT_MATCHING)
def test_a_request_about_something_else_pulls_nothing(request_text):
    assert studio_atlas.select(request_text) == ("", [])


def test_a_composite_request_can_pull_two_systems_and_respects_the_budget():
    text = "Build a shop with a ProcessReceipt handler where players buy items into an inventory with stackable slots"
    _block, used = studio_atlas.select(text, max_chars=20000)
    assert {s.id for s in used} == {"shop", "inventory"}
    block, used = studio_atlas.select(text, max_chars=3000)
    assert used and len(block) <= 3000 and "(truncated)" in block
    assert studio_atlas.select(text, max_chars=500) == ("", [])
    assert studio_atlas.select("   ") == ("", [])


def test_missing_atlas_gives_nothing(tmp_path):
    assert studio_atlas.select("save player data with datastore", root=tmp_path) == ("", [])


def test_short_tags_match_whole_words_only():
    uikit = next(s for s in SYSTEMS if s.id == "uikit")
    assert studio_atlas.score("a ui", uikit) == 1
    assert studio_atlas.score("a fluid guitar build", uikit) == 0


def _tool(env, names):
    found = os.environ.get(env) or next(filter(None, (shutil.which(n) for n in names)), None)
    if not found:
        candidate = ROOT.parent / "tools-portable" / "lune-0.11.0" / "lune.exe"
        found = str(candidate) if env == "STAR_LUNE" and candidate.is_file() else None
    return found


@pytest.mark.parametrize("system", SYSTEMS, ids=lambda s: s.id)
def test_every_system_passes_its_lune_tests(system):
    lune = _tool("STAR_LUNE", ["lune"])
    if not lune:
        pytest.skip("Lune is not installed (set STAR_LUNE)")
    test = ATLAS / system.test
    done = subprocess.run([lune, "run", test.name], cwd=test.parent, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and f"{system.id}:" in done.stdout and " 0 failed" in done.stdout, done.stdout + done.stderr


@pytest.mark.parametrize("system", SYSTEMS, ids=lambda s: s.id)
def test_every_module_is_clean_under_luau_analyze_strict(system):
    analyze = _tool("STAR_LUAU_ANALYZE", ["luau-analyze"])
    if not analyze:
        pytest.skip("luau-analyze is not installed (set STAR_LUAU_ANALYZE)")
    done = subprocess.run([analyze, "--mode=strict", str(ATLAS / system.module)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and not (done.stdout + done.stderr).strip(), done.stdout + done.stderr


def test_setting_defaults_on_and_is_validated():
    from star.desktop_core import Settings
    assert Settings().studio_atlas is True
    with pytest.raises(ValueError):
        Settings(studio_atlas="yes").validate()


def test_run_task_adds_the_atlas_only_for_matching_roblox_turns_and_only_when_enabled(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from star import agent, desktop_core as core
    monkeypatch.setattr(core, "app_data", lambda: tmp_path / "home")
    seen, events = [], []

    @asynccontextmanager
    async def model_client(settings, **kwargs):
        yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=None)))

    async def fake_execute(**kwargs):
        seen.append(agent.final_user_text(kwargs["prompt"], agent.volatile_context(
            kwargs["turn_sections"], limit=kwargs["turn_context_chars"])))
        return "answer", [{"role": "assistant", "content": "answer"}], []

    monkeypatch.setattr(core, "open_client", model_client)
    monkeypatch.setattr(core, "execute", fake_execute)
    base = core.Settings(model="model", knowledge_endpoint="off")
    prompt = "Write a Roblox Luau script that saves player data with DataStoreService UpdateAsync and BindToClose"
    assert core.run_task(base, prompt, mode="auto", on_event=events.append) == "answer"
    assert studio_atlas.HEADING in seen[-1] and "Session-locked DataStore profile" in seen[-1]
    used = [e for e in events if e.get("event") == "studio_atlas_used"]
    assert used and used[-1]["ids"] == ["profile"]
    core.run_task(base, "Write a short poem about the sea", mode="auto")
    assert studio_atlas.HEADING not in seen[-1]
    base.studio_atlas = False
    core.run_task(base, prompt, mode="auto")
    assert studio_atlas.HEADING not in seen[-1]
