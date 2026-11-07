"""Regression tests for host-grounded inspect-before-edit Studio script writes."""
from __future__ import annotations

import pytest

from star import studio_loop as sl
from tests.studio_fake import FakeStudio, TOOLS, text
from tests.test_studio_loop import opened, run

PATH = "ServerScriptService.Main"


def existing():
    fake = FakeStudio()
    fake.marker = True  # Existing content is permitted only in a STAR-owned sandbox.
    fake.scripts[PATH] = {"class": "Script", "source": "print(1)"}
    studio = run(opened(fake))
    assert studio.verdict.editable
    return fake, studio


def patch(fake):
    return {
        "studio_id": fake.studio_id, "datamodel_type": "Edit", "file_path": PATH,
        "edits": [{"old_string": "print(1)", "new_string": "print(2)"}],
    }


def test_existing_script_inspected_before_native_write():
    fake, studio = existing()
    result = run(studio.call_tool("multi_edit", patch(fake)))
    assert not sl.result_failed(result)
    assert fake.scripts[PATH]["source"] == "print(2)"
    inspect_position = fake.names().index("inspect_instance")
    assert fake.calls[inspect_position][1]["path"] == PATH
    assert inspect_position < len(fake.names()) - 1
    assert fake.names()[-1] == "execute_luau"
    assert studio.journal.report()["inspection"] == {
        "existing_scripts_inspected": 1, "new_script_paths": 0, "unscoped_luau_edits": 0
    }


@pytest.mark.parametrize("reply", [
    text("Not found", True),
    text(""),
    text("Not found"),
    text({"path": "ServerScriptService.Different", "className": "Script"}),
    text({"path": PATH, "className": "Folder"}),
    text({"path": 123, "className": "Script"}),
])
def test_missing_wrong_or_unreliable_inspection_refuses_all_writes(reply):
    fake, studio = existing()
    fake._inspect_instance = lambda _: reply
    result = run(studio.call_tool("multi_edit", patch(fake)))
    assert sl.result_failed(result)
    assert fake.scripts[PATH]["source"] == "print(1)"
    assert fake.names()[-1] == "inspect_instance"  # no native script mutation followed
    assert studio.journal.entries == []


def test_existing_edit_refuses_without_inspection_capability():
    fake = FakeStudio(tools=[tool for tool in TOOLS if tool["name"] != "inspect_instance"])
    fake.marker = True
    fake.scripts[PATH] = {"class": "Script", "source": "print(1)"}
    studio = run(opened(fake))
    result = run(studio.call_tool("multi_edit", patch(fake)))
    assert sl.result_failed(result)
    assert fake.scripts[PATH]["source"] == "print(1)"
    assert not studio.journal.entries


def test_new_script_is_not_falsely_reported_as_existing_inspection():
    fake = FakeStudio()
    studio = run(opened(fake))
    result = run(studio.call_tool("multi_edit", {
        "studio_id": fake.studio_id, "datamodel_type": "Edit",
        "file_path": PATH, "className": "Script",
        "edits": [{"old_string": "", "new_string": "print(1)"}],
    }))
    assert not sl.result_failed(result)
    assert "inspect_instance" not in fake.names()
    assert studio.journal.report()["inspection"] == {
        "existing_scripts_inspected": 0, "new_script_paths": 1, "unscoped_luau_edits": 0
    }


def test_raw_luau_does_not_claim_inspection_coverage():
    fake = FakeStudio()
    studio = run(opened(fake))
    result = run(studio.call_tool("execute_luau", {
        "studio_id": fake.studio_id, "datamodel_type": "Edit", "code": "print('hello')"
    }))
    assert not sl.result_failed(result)
    assert studio.journal.report()["inspection"]["unscoped_luau_edits"] == 1
