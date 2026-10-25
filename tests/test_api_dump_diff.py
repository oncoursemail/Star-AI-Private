"""API dump freshness diff (star/api_dump_diff.py, issue #555): what a new dump added or deprecated, and that both
refresh scripts list it and queue it for night school."""
import copy
import json

from scripts import refresh_roblox_api as refresh
from star import api_dump_diff, curiosity, roblox_api_dataset as dataset, roblox_deprecated


def member(name, kind="Function", **extra):
    return {"Name": name, "MemberType": kind, **extra}


def dump(version="0.1.0.1", **classes):
    return {"Version": 1, "StarSource": {"studioVersion": version, "generated": "2026-10-01"},
            "Classes": [{"Name": n, "Superclass": "Instance", "Tags": [], "Members": m} for n, m in classes.items()],
            "Enums": [{"Name": "Mode", "Items": [{"Name": "A", "Value": 1}]}]}


OLD = dump(Part=[member("Touch"), member("Old", "Property")], Tool=[member("Equip")])


def newer():
    new = copy.deepcopy(OLD)
    new["StarSource"]["studioVersion"] = "0.2.0.2"
    new["Classes"][0]["Members"] += [member("Glow", "Property"), member("Pulse")]            # two new Part members
    new["Classes"][0]["Members"][1]["Tags"] = ["Deprecated"]                                  # Part.Old deprecated
    new["Classes"][0]["Members"][1]["PreferredDescriptorName"] = "Fresh"
    new["Classes"][1]["Members"].pop()                                                        # Tool.Equip removed
    new["Classes"].append({"Name": "Hologram", "Superclass": "Part", "Tags": [], "Members": [member("Beam")]})
    new["Enums"][0]["Items"].append({"Name": "B", "Value": 2})
    new["Enums"].append({"Name": "Fresh", "Items": []})
    return new


def test_diff_lists_added_removed_and_deprecated_members_and_new_classes():
    changes = api_dump_diff.diff_dumps(OLD, newer())
    assert changes["added_classes"] == ["Hologram (Part)"]
    assert changes["added_members"] == ["Part.Glow (Property)", "Part.Pulse (Function)"]      # not Hologram.Beam: a new class
    assert changes["newly_deprecated"] == ["Part.Old -> Fresh"]
    assert changes["removed_members"] == ["Tool.Equip (Function)"]
    assert changes["added_enums"] == ["Fresh"] and changes["added_enum_items"] == ["Enum.Mode.B"]
    assert (changes["old"]["studioVersion"], changes["new"]["studioVersion"]) == ("0.1.0.1", "0.2.0.2")
    assert not api_dump_diff.has_changes(api_dump_diff.diff_dumps(OLD, OLD))


def test_a_member_added_already_deprecated_counts_as_deprecated_too():
    new = copy.deepcopy(OLD)
    new["Classes"][0]["Members"].append(member("Legacy", "Property", Tags=["Deprecated"]))
    assert api_dump_diff.diff_dumps(OLD, new)["newly_deprecated"] == ["Part.Legacy"]


def test_changes_file_caps_lists_but_keeps_the_totals(tmp_path):
    changes = {"old": {}, "new": {}, "added_members": [f"C.m{i} (Function)" for i in range(300)]}
    path = api_dump_diff.write_changes(changes, tmp_path / "changes.json", today="2026-10-25")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored["added_members"]) == api_dump_diff.LIST_LIMIT and stored["added_members_total"] == 300


def test_queueing_groups_members_per_class_and_names_deprecations(tmp_path):
    path = tmp_path / "q.jsonl"
    changes = api_dump_diff.diff_dumps(OLD, newer())
    assert api_dump_diff.queue_changes(changes, path=path) == 3
    topics = sorted(i.topic for i in curiosity.load(path).values())
    assert topics == ["Roblox API deprecated: Part.Old -> Fresh", "new Roblox API members on Part: Glow, Pulse",
                      "new Roblox class Hologram (Part)"]
    assert {i.kind for i in curiosity.load(path).values()} == {"api_change"}
    # the same change twice is one item seen twice, not two items
    api_dump_diff.queue_changes(changes, path=path)
    assert sorted(i.count for i in curiosity.load(path).values()) == [2, 2, 2]


def test_the_refresh_script_lists_stores_and_queues_the_changes_before_replacing_the_old_dump(tmp_path, capsys):
    real = json.loads(dataset.DATA.read_text(encoding="utf-8"))
    out = tmp_path / "roblox_api.json"
    older = copy.deepcopy(real)
    gone = older["Classes"][1]["Members"].pop()              # the "previous" dump lacks one member
    out.write_text(refresh.render(refresh.compact(older), older["StarSource"]), encoding="utf-8")
    source = tmp_path / "dump.json"
    source.write_text(json.dumps(real), encoding="utf-8")
    assert refresh.main(["--input", str(source), "--version-upload", "version-0123456789abcdef",
                         "--studio-version", "0.9.0.1", "--output", str(out)]) == 0
    said = capsys.readouterr().out
    assert "API changes: 0 classes, 1 members added" in said
    stored = json.loads((tmp_path / "changes.json").read_text(encoding="utf-8"))
    assert stored["added_members"] == [f"{older['Classes'][1]['Name']}.{gone['Name']} ({gone['MemberType']})"]
    assert [i.kind for i in curiosity.load().values()] == ["api_change"]            # the machine's own queue (conftest: tmp)
    # a refresh that changed nothing says so and queues nothing more
    before = sum(i.count for i in curiosity.load().values())
    assert refresh.main(["--input", str(source), "--version-upload", "version-0123456789abcdef",
                         "--studio-version", "0.9.0.1", "--output", str(out)]) == 0
    assert "no API changes" in capsys.readouterr().out
    assert sum(i.count for i in curiosity.load().values()) == before


def test_the_deprecated_inventory_refresh_queues_newly_listed_members(tmp_path):
    def page(*rows):
        head = "## Deprecated Properties\n| Class/Type | Member | Replacement | Note |\n|---|---|---|---|\n"
        return head + "".join(f"| Cls{i} | `Prop{i}` | *(none)* | Deprecated. |\n" for i in range(100)) + \
            "".join(f"| {owner} | `{name}` | `{repl}` | Use {repl}. |\n" for owner, name, repl in rows)
    path = tmp_path / "deprecated.json"
    roblox_deprecated.refresh(page(), path=path, today="2026-10-01")
    assert curiosity.load() == {}                              # the first file has nothing to compare with
    data = roblox_deprecated.refresh(page(("Part", "Shiny", "Sparkle")), path=path, today="2026-10-25")
    assert data["newly_listed"] == ["Part.Shiny -> Sparkle"]
    assert [i.topic for i in curiosity.load().values()] == ["Roblox API deprecated: Part.Shiny -> Sparkle"]
