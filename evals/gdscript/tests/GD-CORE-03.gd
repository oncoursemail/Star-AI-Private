extends SceneTree
## GD-CORE-03: match on typeof with numeric-only summing that ignores bool. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var c = S.new()
    H.check("scalars", c.classify(null) == "nil" and c.classify(true) == "bool" and c.classify(3) == "int" and c.classify(2.5) == "float")
    H.check("string and vector2", c.classify("x") == "string" and c.classify(Vector2(1, 2)) == "vector2")
    H.check("containers", c.classify([1]) == "array" and c.classify({"a": 1}) == "dictionary")
    var node := Node.new()
    H.check("object", c.classify(node) == "object")
    node.free()
    H.check("other", c.classify(Vector3.ZERO) == "other" and c.classify(Color.RED) == "other")
    H.check("sum skips non-numbers", is_equal_approx(c.sum_numbers([1, 2.5, "x", true, null, [4]]), 3.5))
    H.check("sum of nothing", c.sum_numbers([]) == 0.0 and typeof(c.sum_numbers([])) == TYPE_FLOAT)
    H.finish(self)
