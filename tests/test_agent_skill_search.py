"""Offline tests for metadata-only Agent Skill retrieval and Tool Workshop integration."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from star.agent_skills import SkillLibrary
from star.tool_workshop import ToolWorkshop


def _write_skill(root: Path, name: str, description: str, body: str = "Private body text.") -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8",
    )


def _library(tmp_path: Path) -> SkillLibrary:
    home = tmp_path / "home"
    skills = home / "skills"
    _write_skill(
        skills,
        "roblox-secure-remotes",
        "Validate Roblox RemoteEvent payloads on the server and prevent exploit abuse.",
        "Never trust client input. Validate types, ranges, ownership and cooldowns.",
    )
    _write_skill(
        skills,
        "roblox-ui-craft",
        "Design responsive Roblox interfaces, menus, HUDs and accessible layouts.",
        "Use native GUI objects and inspect multiple viewport sizes.",
    )
    _write_skill(
        skills,
        "python-typing",
        "Improve Python annotations, static typing and typed API design.",
        "Use precise types and narrow optional values.",
    )
    return SkillLibrary(workspace=None, home=home)


def test_search_ranks_title_and_description_matches(tmp_path):
    library = _library(tmp_path)
    results = library.search("Roblox RemoteEvent server validate security", limit=3)

    assert results[0]["name"] == "roblox-secure-remotes"
    assert results[0]["score"] > results[1]["score"]
    assert {"roblox", "remoteevent", "server", "validate"} <= set(results[0]["matched_terms"])


def test_search_supports_description_only_matches(tmp_path):
    library = _library(tmp_path)
    results = library.search("responsive menus accessible interface layouts")

    assert results
    assert results[0]["name"] == "roblox-ui-craft"


def test_search_is_deterministic_and_respects_limit(tmp_path):
    library = _library(tmp_path)
    first = library.search("Roblox server security", limit=2)
    second = library.search("Roblox server security", limit=2)

    assert first == second
    assert len(first) <= 2


def test_search_returns_metadata_only_not_body_or_paths(tmp_path):
    library = _library(tmp_path)
    result = library.search("Roblox RemoteEvent server")[0]

    assert result["source"] == "personal"
    assert "Private body text" not in str(result)
    assert "Never trust client input" not in str(result)
    assert "file" not in result
    assert "path" not in result
    assert "score" in result
    assert "matched_terms" in result


def test_project_skill_overrides_personal_copy(tmp_path):
    workspace = tmp_path / "project"
    home = tmp_path / "home"
    _write_skill(
        workspace / ".agents" / "skills",
        "project-api-review",
        "Review the current project API contracts and compatibility.",
        "Project-specific instructions.",
    )
    _write_skill(
        home / "skills",
        "project-api-review",
        "Generic API review skill.",
        "Personal copy should not win.",
    )
    library = SkillLibrary(workspace=workspace, home=home)

    results = library.search("project API compatibility review")

    assert results[0]["name"] == "project-api-review"
    assert results[0]["source"] == "project"


def test_search_returns_empty_for_no_matching_skill(tmp_path):
    assert _library(tmp_path).search("volcanic submarine cooking") == []


@pytest.mark.parametrize("query", ["", " ", "the and with", "x", "a" * 201, None])
def test_search_rejects_invalid_queries(tmp_path, query):
    with pytest.raises(ValueError):
        _library(tmp_path).search(query)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 21, 1.5, None])
def test_search_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError):
        _library(tmp_path).search("Roblox UI", limit=limit)


def test_tool_workshop_skills_source_uses_ranked_search(tmp_path):
    library = _library(tmp_path)
    intelligence = SimpleNamespace(skills=library, vault=None, graph=None)
    workshop = ToolWorkshop(
        home=tmp_path / "profile",
        project="STAR",
        intelligence=intelligence,
    )
    try:
        proposal = workshop.propose(
            "find-relevant-skills",
            "Find the most relevant installed Agent Skills for a task",
            [{"source": "skills", "limit": 3}],
        )
        result = workshop.run(
            proposal["id"], "Roblox RemoteEvent server validation", preview=True
        )
        records = result["results"][0]["records"]

        assert result["ok"] is True
        assert records[0]["name"] == "roblox-secure-remotes"
        assert records[0]["score"] > 0
    finally:
        workshop.db.close()


def test_catalog_reads_only_bounded_frontmatter_prefix(tmp_path, monkeypatch):
    library = _library(tmp_path)
    original_open = Path.open
    read_sizes = []

    class TrackingReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.handle.close()
            return False

        def read(self, size=-1):
            read_sizes.append(size)
            return self.handle.read(size)

    def tracking_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path.name == "SKILL.md":
            return TrackingReader(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    assert library.search("Roblox RemoteEvent server")
    assert read_sizes
    assert set(read_sizes) == {8007}
