extends SceneTree
## GD-CORE-02: Enum with wrap-around arithmetic, vectors and an out-of-range name. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var d = S.new()
    H.check("turn_right wraps", d.turn_right(0) == 1 and d.turn_right(3) == 0)
    H.check("turn_left wraps", d.turn_left(0) == 3 and d.turn_left(2) == 1)
    H.check("opposite", d.opposite(0) == 2 and d.opposite(1) == 3 and d.opposite(3) == 1)
    H.check("to_vector", d.to_vector(0) == Vector2i(0, -1) and d.to_vector(1) == Vector2i(1, 0) and d.to_vector(2) == Vector2i(0, 1) and d.to_vector(3) == Vector2i(-1, 0))
    H.check("name_of", d.name_of(2) == "DOWN" and d.name_of(0) == "UP" and d.name_of(3) == "LEFT")
    H.check("name_of out of range", d.name_of(7) == "UNKNOWN" and d.name_of(-1) == "UNKNOWN")
    var consts: Dictionary = S.get_script_constant_map()
    H.check("enum Direction declared in order", consts.has("Direction") and consts["Direction"].get("UP", -1) == 0 and consts["Direction"].get("LEFT", -1) == 3)
    H.finish(self)
