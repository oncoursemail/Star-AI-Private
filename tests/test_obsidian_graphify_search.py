"""Search quality of the Obsidian vault bridge and the Graphify adapter on the shapes the brain vault produces."""
import json
import os
from pathlib import Path

from star import graphify_bridge
from star.graphify_bridge import GraphifyGraph
from star.obsidian_bridge import ObsidianVault


def _vault(root: Path, notes: dict[str, str]) -> ObsidianVault:
    for rel, text in notes.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return ObsidianVault(root)


def test_question_words_do_not_outrank_the_rare_word(tmp_path):
    notes = {f"filler{i}.md": "how does this work and what is it for? " * 30 for i in range(6)}
    notes["forge.md"] = "# Forge\n\nGit over ssh listens on port 2222."
    hit = _vault(tmp_path, notes).search("how does the forge work")
    assert hit["notes"][0]["path"] == "forge.md"


def test_a_title_or_file_name_match_beats_a_passing_mention(tmp_path):
    vault = _vault(tmp_path, {
        "notes/budget.md": "# Budget\n\nOne line about the conductor in passing.",
        "notes/conductor.md": "# Night conductor\n\nWrites practice tasks.",
        "notes/long.md": "# Misc\n\n" + "conductor " * 4 + "filler " * 200})
    assert [n["path"] for n in vault.search("conductor")["notes"]][0] == "notes/conductor.md"


def test_underscores_plurals_and_endings_match(tmp_path):
    vault = _vault(tmp_path, {"a.md": "# A\n\nThe priority_proxy pauses background streams while an owner request runs.",
                              "b.md": "# B\n\nUnrelated text about voices."})
    assert vault.search("priority proxy")["notes"][0]["path"] == "a.md"
    assert vault.search("pausing stream")["notes"][0]["path"] == "a.md"


def test_search_follows_edits_and_new_notes_without_a_restart(tmp_path):
    vault = _vault(tmp_path, {"a.md": "# A\n\nAlpha only."})
    assert vault.search("zebra")["notes"] == []
    (tmp_path / "b.md").write_text("# B\n\nA zebra appears.", encoding="utf-8")
    assert vault.search("zebra")["notes"][0]["path"] == "b.md"
    os.utime(tmp_path / "a.md", ns=(10**18, 10**18))
    (tmp_path / "a.md").write_text("# A\n\nNow the zebra is here too, zebra zebra.", encoding="utf-8")
    assert {n["path"] for n in vault.search("zebra")["notes"]} == {"a.md", "b.md"}


def test_hidden_folders_and_a_question_made_only_of_stop_words(tmp_path):
    vault = _vault(tmp_path, {".obsidian/x.md": "zebra private", "n.md": "# N\n\nHow is it?"})
    assert vault.search("zebra")["notes"] == []
    assert vault.search("how is it")["notes"][0]["path"] == "n.md"       # falls back to the words it was given


def _graph(root: Path, nodes: list[dict], links: list[dict] | None = None) -> GraphifyGraph:
    out = root / "graphify-out"
    out.mkdir(exist_ok=True)
    (out / "graph.json").write_text(json.dumps({"directed": False, "nodes": nodes, "links": links or []}), encoding="utf-8")
    return GraphifyGraph(root)


def test_a_file_named_with_underscores_answers_a_plain_words_question(tmp_path):
    # both labels hold both words; only the second holds them as the phrase "priority proxy" (underscore = space)
    nodes = [{"id": "x", "label": "priority_x_proxy.py", "source_file": "star/priority_x_proxy.py", "file_type": "code"},
             {"id": "pp", "label": "priority_proxy_server_module.py", "source_file": "star/priority_proxy_server_module.py",
              "file_type": "code"},
             {"id": "q", "label": "PriorityQueue", "source_file": "benchmarks/h02.luau", "file_type": "code"}]
    assert _graph(tmp_path, nodes).query("priority proxy")["matches"][0]["node"]["id"] == "pp"
    assert _graph(tmp_path, nodes).query("priority_proxy")["matches"][0]["node"]["id"] == "pp"


def test_a_graph_the_size_of_the_star_repo_is_accepted(tmp_path):
    # STAR's own code graph is 29 MB; the adapter used to refuse anything over 20 MB
    padding = "x" * 200
    nodes = [{"id": f"n{i}", "label": f"symbol_{i}()", "source_file": f"star/mod_{i % 500}.py", "file_type": "code",
              "pad": padding} for i in range(70_000)]
    graph = _graph(tmp_path, nodes)
    size = (tmp_path / "graphify-out" / "graph.json").stat().st_size
    assert size > 20_000_000 and size <= graphify_bridge.MAX_GRAPH_BYTES
    assert graph.available()
    assert graph.stats()["nodes"] == 70_000
    assert graph.query("symbol_123")["matches"][0]["node"]["id"] == "n123"


def _hub(tmp_path: Path, *, brain: bool):
    from star.intelligence import LocalIntelligence
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n.md").write_text("# Night school\n\nPractice at night.", encoding="utf-8")
    if brain:
        (vault / ".brain-vault.json").write_text("{}", encoding="utf-8")
    return LocalIntelligence(home=tmp_path / "profile", workspace=None, obsidian_vault=vault, skills_enabled=False)


def test_the_brain_vault_answers_team_questions_that_never_say_notes(tmp_path):
    hub = _hub(tmp_path, brain=True)
    for prompt in ("how does night school work", "where is the priority proxy", "what did we change today",
                   "what changed yesterday", "which port does the Metallic forge use"):
        assert "star_obsidian_search" in {t["name"] for t in hub.definitions(prompt)}, prompt
    for prompt in ("how does a TweenService tween work", "write a wave spawner", "How are you?"):
        assert "star_obsidian_search" not in {t["name"] for t in hub.definitions(prompt)}, prompt


def test_an_ordinary_vault_keeps_the_old_trigger(tmp_path):
    hub = _hub(tmp_path, brain=False)
    assert "star_obsidian_search" not in {t["name"] for t in hub.definitions("how does night school work")}
    assert "star_obsidian_search" in {t["name"] for t in hub.definitions("search my notes for night school")}
