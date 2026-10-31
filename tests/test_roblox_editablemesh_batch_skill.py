"""Keep the 2026 geometry guidance discoverable but off unless opted in."""
from star import skill_packs


def test_official_editablemesh_skill_is_bundled_but_not_default():
    names = {pack.name for pack in skill_packs.available()}
    assert "roblox-editablemesh-batching" in names
    assert "roblox-editablemesh-batching" not in skill_packs.DEFAULT_ENABLED


def test_opted_in_skill_selected_for_specific_mesh_batch_question():
    chosen = skill_packs.select(
        "Roblox EditableMesh batching using BatchAdd and BatchSetValues",
        enabled={"roblox-editablemesh-batching"},
    )
    assert [pack.name for pack in chosen] == ["roblox-editablemesh-batching"]
    assert "task.synchronize()" in chosen[0].body


def test_skill_does_not_leak_into_other_conversations():
    assert not skill_packs.select("What is a funny cat?", enabled={"roblox-editablemesh-batching"})
    assert not skill_packs.select("Roblox EditableMesh batch optimization", enabled={"roblox-vfx"})


def test_skill_is_enabled_only_if_explicitly_requested():
    enabled = skill_packs.enabled_names(
        environ={"STAR_SKILL_PACKS": "roblox-editablemesh-batching"}
    )
    assert enabled == frozenset({"roblox-editablemesh-batching"})
