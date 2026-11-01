extends SceneTree
## GD-ARR-01: Non-mutating top-n, chunking and unique sort over arrays. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    var v: Array[int] = [5, 1, 9, 9, 3]
    var before: Array[int] = v.duplicate()
    H.check("top_n", Array(u.top_n(v, 3)) == [9, 9, 5])
    H.check("top_n leaves the input alone", v == before)
    H.check("top_n edges", Array(u.top_n(v, 0)) == [] and Array(u.top_n(v, -2)) == [] and Array(u.top_n(v, 99)) == [9, 9, 5, 3, 1])
    H.check("chunk", Array(u.chunk(v, 2)) == [[5, 1], [9, 9], [3]])
    H.check("chunk edges", Array(u.chunk(v, 0)) == [] and Array(u.chunk(v, 10)) == [[5, 1, 9, 9, 3]] and Array(u.chunk([], 3)) == [])
    H.check("unique_sorted", Array(u.unique_sorted(v)) == [1, 3, 5, 9] and v == before)
    H.check("floats", Array(u.top_n([1.5, 2.5, 0.5], 2)) == [2.5, 1.5])
    H.finish(self)
