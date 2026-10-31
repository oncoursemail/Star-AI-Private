extends SceneTree
## GD-DATA-01: Deep dictionary merge that copies and never mutates its inputs. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    var a := {"hp": 10, "pos": {"x": 1, "y": 2}, "tags": ["a"]}
    var b := {"hp": 12, "pos": {"y": 5, "z": 9}, "tags": ["b", "c"], "new": true}
    var a_before = a.duplicate(true)
    var b_before = b.duplicate(true)
    var m = u.merge_deep(a, b)
    H.check("values from b win", m["hp"] == 12 and m["new"] == true)
    H.check("nested dictionaries merge", m["pos"] == {"x": 1, "y": 5, "z": 9})
    H.check("arrays are replaced", m["tags"] == ["b", "c"])
    H.check("inputs untouched", a == a_before and b == b_before)
    m["pos"]["x"] = 99
    m["tags"].append("z")
    H.check("no sharing with the inputs", a["pos"]["x"] == 1 and not b["pos"].has("x") and a["tags"] == ["a"] and b["tags"] == ["b", "c"])
    var src := {"k": {"n": 1}, "list": [1, 2]}
    var only_a = u.merge_deep(src, {})
    only_a["k"]["n"] = 2
    only_a["list"].append(3)
    H.check("keys only in a are copied deeply", src["k"]["n"] == 1 and src["list"] == [1, 2])
    var only_b = u.merge_deep({}, src)
    only_b["k"]["n"] = 7
    H.check("keys only in b are copied deeply", src["k"]["n"] == 1)
    H.check("a dictionary replaces a plain value", u.merge_deep({"x": 1}, {"x": {"y": 2}}) == {"x": {"y": 2}})
    H.check("a plain value replaces a dictionary", u.merge_deep({"x": {"y": 2}}, {"x": 5}) == {"x": 5})
    H.finish(self)
