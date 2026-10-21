"""server/brain/lookup/build_cache.py: the static n-gram cache file llama.cpp's ngram-cache drafter loads."""
import importlib.util
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_cache", ROOT / "server/brain/lookup/build_cache.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)


def test_bigrams_are_counted_and_written_in_llama_cpps_layout(tmp_path):
    cache = bc.count([[1, 2, 3, 1, 2, 3, 1, 2, 4]])
    assert cache[(1, 2)] == {3: 2, 4: 1} and cache[(2, 3)] == {1: 2} and cache[(3, 1)] == {2: 2}
    path = tmp_path / "c.lcs"
    bc.save({(1, 2): cache[(1, 2)]}, path)
    data = path.read_bytes()
    # common_ngram (4 x int32, unused = -1), int32 entries, then (int32 token, int32 count) pairs
    assert struct.unpack_from("<4ii", data, 0) == (1, 2, -1, -1, 2)
    assert sorted(struct.iter_unpack("<ii", data[20:])) == [(3, 2), (4, 1)]
    bc.save(cache, path)
    assert bc.load(path) == cache


def test_static_draft_uses_llama_cpps_thresholds_for_two_grams():
    from collections import Counter
    assert bc.static_draft(Counter({7: 1})) is None              # one sample: below the 2-sample minimum
    assert bc.static_draft(Counter({7: 2})) == 7
    assert bc.static_draft(Counter({7: 2, 8: 2})) in (7, 8)       # 50 %: allowed (llama.cpp's pick depends on map order)
    assert bc.static_draft(Counter({7: 2, 8: 2, 9: 1})) is None   # 40 %: below 50 %
    proxy = bc.proxy(bc.count([[1, 2, 3, 1, 2, 3]]), [[1, 2, 3, 1, 2, 9]])
    # (1,2) seen twice -> drafts 3 (right once, wrong once); (2,3) and (3,1) seen once -> no draft
    assert proxy == {"tokens": 4, "drafted": 2, "right": 1, "draft_share": 0.5, "right_of_drafted": 0.5}


def test_held_out_prompts_and_their_answers_stay_out_of_the_corpus(tmp_path):
    prompt = "In my Roblox game: write a server ModuleScript PlayerData that keeps each player's data table safe."
    rows = [{"prompt": "Unrelated request about doors", "answer": "```lua\nlocal door = workspace.Door\nprint(door.Name, door.Position)\n```"},
            {"prompt": "Please: " + prompt, "answer": "```lua\nlocal leaked = true -- must not be in the cache\n```"}]
    jsonl = tmp_path / "ex.jsonl"
    jsonl.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "NET-05.md").write_text("```lua\nlocal reference = 'held out answer text'\n```", encoding="utf-8")
    (ref / "NET-06.md").write_text("```luau\nlocal kept = 'another reference answer, long enough'\n```", encoding="utf-8")
    (ref / "NET-06.bad.md").write_text("```lua\nlocal bad = 'a known bad answer, never learnt'\n```", encoding="utf-8")

    from types import SimpleNamespace
    args = SimpleNamespace(jsonl=[str(jsonl)], reference_dir=str(ref), docs="", api="")
    docs, kinds = bc.collect(args, [{"id": "NET-05", "prompt": prompt}])
    text = "\n".join(docs)
    assert "workspace.Door" in text and "another reference answer" in text
    assert "leaked" not in text and "held out answer" not in text and "known bad" not in text
    assert kinds["dropped_overlap"] == 1


def test_api_dump_becomes_luau_shaped_lines():
    dump = {"Classes": [{"Name": "Players", "Tags": ["Service"], "Members": [
        {"MemberType": "Event", "Name": "PlayerAdded"},
        {"MemberType": "Function", "Name": "GetPlayerByUserId", "Parameters": [{"Name": "userId"}]}]}],
            "Enums": [{"Name": "KeyCode", "Items": [{"Name": "E"}]}]}
    assert bc.api_lines(dump) == ['local Players = game:GetService("Players")', "Players.PlayerAdded:Connect(function()",
                                  "Players:GetPlayerByUserId(userId)", "Enum.KeyCode.E"]
