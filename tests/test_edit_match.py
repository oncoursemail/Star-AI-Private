"""Tolerant find-and-replace edits (star/edit_match.py), the workspace_edit tool, lint-on-edit and the Studio path."""
import asyncio

import pytest

from star import studio_loop as sl
from star.edit_match import EditMismatch, apply_edit
from star.studio import list_tools
from star.workspace import TOOL_NAMES, WRITE_TOOLS, Workspace
from tests.studio_fake import FakeStudio

LUAU = (
    "local Players = game:GetService(\"Players\")\n"
    "\n"
    "local function onJoin(player)\n"
    "    local stats = Instance.new(\"Folder\")\n"
    "    stats.Name = \"leaderstats\"\n"
    "    stats.Parent = player\n"
    "end\n"
    "\n"
    "Players.PlayerAdded:Connect(onJoin)\n"
)


# ------------------------------------------------------------------ exact matches keep their old meaning

def test_an_exact_unique_match_is_replaced_once():
    result = apply_edit(LUAU, 'stats.Name = "leaderstats"', 'stats.Name = "Stats"')
    assert result.strategy == "exact" and result.count == 1
    assert 'stats.Name = "Stats"' in result.text and result.text.count("\n") == LUAU.count("\n")


def test_replace_all_replaces_every_exact_occurrence():
    result = apply_edit("a = 1\na = 1\n", "a = 1", "a = 2", replace_all=True)
    assert result.text == "a = 2\na = 2\n" and result.count == 2


def test_two_exact_places_without_replace_all_are_refused_as_ambiguous():
    with pytest.raises(EditMismatch, match="occurs 2 times"):
        apply_edit("a = 1\na = 1\n", "a = 1", "a = 2")


@pytest.mark.parametrize("old, new", [("", "x"), ("same", "same")])
def test_empty_or_unchanged_edits_are_refused(old, new):
    with pytest.raises(EditMismatch):
        apply_edit("same", old, new)


# ------------------------------------------------------------------ the whitespace slips small models make

def test_a_block_at_the_wrong_indentation_is_found_and_re_indented():
    old = 'local stats = Instance.new("Folder")\nstats.Name = "leaderstats"\n'      # model dropped the indent
    new = 'local stats = Instance.new("Folder")\nstats.Name = "leaderstats"\nif true then\n    stats:SetAttribute("v", 1)\nend\n'
    result = apply_edit(LUAU, old, new)
    assert result.strategy == "whitespace"
    assert ('    stats.Name = "leaderstats"\n    if true then\n        stats:SetAttribute("v", 1)\n    end\n'
            '    stats.Parent = player\n') in result.text


def test_trailing_spaces_and_tabs_for_the_whole_block_are_tolerated():
    source = "if ready then\n\tfire()\n\tdone()\nend\n"
    result = apply_edit(source, "    fire()   \n    done()", "    fire(true)\n    done()")
    assert result.strategy == "whitespace" and result.text == "if ready then\n\tfire(true)\n\tdone()\nend\n"


def test_crlf_files_accept_lf_edits_and_keep_crlf():
    source = LUAU.replace("\n", "\r\n")
    result = apply_edit(source, 'stats.Name = "leaderstats"\n    stats.Parent', 'stats.Name = "x"\n    stats.Parent')
    assert result.strategy == "line_endings" and "\r\n" in result.text and "\n" not in result.text.replace("\r\n", "")
    shifted = apply_edit(source, 'stats.Name = "leaderstats"\nstats.Parent = player', 'stats.Parent = player')
    assert shifted.strategy == "whitespace" and '\r\n    stats.Parent = player\r\nend' in shifted.text
    assert "leaderstats" not in shifted.text and "\n" not in shifted.text.replace("\r\n", "")


def test_a_deletion_removes_the_whole_matched_lines():
    result = apply_edit(LUAU, '	stats.Name = "leaderstats"', "")
    assert result.strategy == "whitespace" and "leaderstats" not in result.text
    assert result.text.count("\n") == LUAU.count("\n") - 1


def test_a_match_on_the_last_line_without_a_newline_stays_without_one():
    result = apply_edit("a()\n  b()", "b()", "c()")
    assert result.text == "a()\n  c()"
    assert apply_edit("a()\n    b()", "  b()  ", "c()").text == "a()\n    c()"


def test_two_places_that_match_once_whitespace_is_ignored_are_refused():
    source = "if a then\n    go()\nend\nif b then\n        go()\nend\n"
    with pytest.raises(EditMismatch, match="several places"):
        apply_edit(source, "	go()  ", "stop()")


def test_part_of_a_line_is_never_matched_loosely():
    with pytest.raises(EditMismatch):
        apply_edit(LUAU, 'Name   = "leaderstats"', 'Name = "x"')


def test_different_relative_indentation_is_not_a_match():
    with pytest.raises(EditMismatch):
        apply_edit(LUAU, 'local stats = Instance.new("Folder")\nstats.Name = "leaderstats"\n  stats.Parent = player', "x")


def test_a_miss_shows_the_closest_lines_to_copy():
    with pytest.raises(EditMismatch) as caught:
        apply_edit(LUAU, 'stats.Name = "leaderstat"\nstats.Parent = plr', "x")
    message = str(caught.value)
    assert "not found" in message and "lines 5-6" in message and 'stats.Name = "leaderstats"' in message


def test_an_unrelated_miss_gets_no_misleading_hint():
    with pytest.raises(EditMismatch) as caught:
        apply_edit(LUAU, "zzzz qqqq wwww", "x")
    assert "Closest" not in str(caught.value)


# ------------------------------------------------------------------ workspace_edit and lint-on-edit

def test_workspace_edit_is_a_write_tool_and_needs_edit_mode(tmp_path):
    assert "workspace_edit" in TOOL_NAMES and WRITE_TOOLS == {"workspace_write", "workspace_edit"}
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(PermissionError):
        Workspace(tmp_path).call("workspace_edit", {"path": "a.txt", "old_string": "hello", "new_string": "bye"})
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


def test_workspace_edit_changes_one_place_and_reports_how_it_matched(tmp_path):
    (tmp_path / "main.py").write_bytes(b"def f():\r\n    return 1\r\n")
    result = Workspace(tmp_path).call("workspace_edit", {"path": "main.py", "old_string": "return 1",
                                                         "new_string": "return 2"}, allow_write=True)
    # The write still reports the original edit contract, now with parser evidence.
    assert {key: result[key] for key in ("path", "bytes_written", "replacements", "match")} == {
        "path": "main.py", "bytes_written": 24, "replacements": 1, "match": "exact"}
    assert result["validation"]["status"] == "passed"
    assert result["validation"]["runtime_verified"] is False
    assert (tmp_path / "main.py").read_bytes() == b"def f():\r\n    return 2\r\n"


def test_workspace_edit_refuses_missing_files_and_bad_matches_with_a_reason(tmp_path):
    workspace = Workspace(tmp_path)
    with pytest.raises((ValueError, OSError)):
        workspace.call("workspace_edit", {"path": "nope.lua", "old_string": "a", "new_string": "b"}, allow_write=True)
    (tmp_path / "a.lua").write_text("print(1)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not found"):
        workspace.call("workspace_edit", {"path": "a.lua", "old_string": "warn(1)", "new_string": "b"}, allow_write=True)
    (tmp_path / ".env").write_text("a", encoding="utf-8")
    with pytest.raises(PermissionError):
        workspace.call("workspace_edit", {"path": ".env", "old_string": "a", "new_string": "b"}, allow_write=True)


def test_written_luau_comes_back_with_lint_findings_and_other_files_do_not(tmp_path):
    workspace = Workspace(tmp_path)
    risky = 'local ds = game:GetService("DataStoreService"):GetDataStore("x")\nds:SetAsync("k", 1)\n'
    linted = workspace.call("workspace_write", {"path": "save.server.luau", "content": risky}, allow_write=True)
    assert linted["lint"] and {"line", "rule", "severity", "message", "fix"} <= set(linted["lint"][0])
    plain = workspace.call("workspace_write", {"path": "notes.txt", "content": risky}, allow_write=True)
    assert "lint" not in plain
    clean = workspace.call("workspace_write", {"path": "ok.luau", "content": "return 1\n"}, allow_write=True)
    assert "lint" not in clean


# ------------------------------------------------------------------ the Studio script edit uses the same matcher

def _studio(source):
    fake = FakeStudio()
    fake.marker = True
    fake.scripts["ServerScriptService.Main"] = {"class": "Script", "source": source}
    studio = asyncio.run(sl.open_guarded(fake, asyncio.run(list_tools(fake)), studio_id=fake.studio_id, opted_in=True))
    return fake, studio


def _edit(studio, fake, old, new):
    return asyncio.run(studio.call_tool("multi_edit", {
        "studio_id": fake.studio_id, "datamodel_type": "Edit", "file_path": "game.ServerScriptService.Main",
        "edits": [{"old_string": old, "new_string": new}]}))


def test_a_studio_edit_with_the_wrong_indentation_lands_once_and_is_journaled():
    fake, studio = _studio("if ready then\n    fire()\nend")
    _edit(studio, fake, "fire()\n", "fire(true)\n")
    assert fake.scripts["ServerScriptService.Main"]["source"] == "if ready then\n    fire(true)\nend"
    assert studio.journal.entries[-1]["after"] == "if ready then\n    fire(true)\nend"


def test_an_ambiguous_studio_edit_is_refused_and_not_journaled():
    fake, studio = _studio("go()\ngo()")
    result = _edit(studio, fake, "go()", "stop()")
    assert result.model_dump()["isError"] and "occurs 2 times" in str(result.model_dump())
    assert studio.journal.entries == [] and fake.scripts["ServerScriptService.Main"]["source"] == "go()\ngo()"
