"""Inspect before code (star/studio_inspect.py) with a fake guarded Studio connection."""
import asyncio
import json

from star import studio_inspect as si
from star.desktop_core import Settings


class FakeStudio:
    studio_id = "studio-1"

    def __init__(self, rows=None, scripts=None, fail=False):
        self.rows, self.scripts, self.fail, self.calls = rows or [], scripts or [], fail, []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail:
            raise OSError("Studio went away")
        data = self.scripts if arguments.get("instance_type") == "BaseScript" else self.rows
        return {"content": [{"type": "text", "text": json.dumps(data)}]}


def test_keywords_prefer_quoted_and_camel_case_names_and_drop_filler():
    words = si.keywords('Make the "Lobby Door" open when a player touches DoorButton and add a coin counter')
    assert words[:2] == ["Lobby Door", "DoorButton"] and "door" in words
    assert "make" not in words and "the" not in words and len(words) <= si.MAX_KEYWORDS


def test_scene_section_lists_matching_objects_and_existing_scripts_with_paths():
    studio = FakeStudio(rows=[{"fullPath": "Workspace.Lobby.Door", "className": "Model", "childSummary": "3 children (3 Part)"},
                              {"fullPath": "CoreGui.Door", "className": "Frame"}],
                        scripts=[{"fullPath": "ServerScriptService.DoorController", "className": "Script"}])
    text = asyncio.run(si.scene_section(studio, "make the door open when touched"))
    assert "- Workspace.Lobby.Door (Model, 3 children (3 Part))" in text
    assert "- ServerScriptService.DoorController (Script)" in text and "CoreGui" not in text
    assert [c[1].get("keywords") for c in studio.calls][0] and all(c[0] == "search_game_tree" for c in studio.calls)
    assert all(c[1]["studio_id"] == "studio-1" and c[1]["datamodel_type"] == "Edit" for c in studio.calls)
    assert len(text) <= si.MAX_CHARS


def test_nothing_found_or_studio_failure_gives_no_section():
    assert asyncio.run(si.scene_section(FakeStudio(), "make a door")) == ""
    assert asyncio.run(si.scene_section(FakeStudio(fail=True), "make a door")) == ""


def test_setting_is_off_by_default():
    assert Settings().studio_inspect is False
    Settings(studio_inspect=True).validate()
