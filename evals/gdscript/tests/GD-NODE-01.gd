extends SceneTree
## GD-NODE-01: Recursive scene-tree walk: count nodes by class and measure depth. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    var root := Node2D.new()
    var a := Sprite2D.new()
    var b := Sprite2D.new()
    var c := Node2D.new()
    var d := Timer.new()
    var e := Node.new()
    root.add_child(a)
    root.add_child(b)
    root.add_child(c)
    c.add_child(d)
    d.add_child(e)
    H.check("counts by class", u.count_by_class(root) == {"Node2D": 2, "Sprite2D": 2, "Timer": 1, "Node": 1})
    H.check("deepest", u.deepest(root) == 3)
    H.check("deepest of a subtree", u.deepest(c) == 2 and u.deepest(a) == 0)
    H.check("single node", u.count_by_class(e) == {"Node": 1})
    H.check("a subtree counts only itself and below", u.count_by_class(c) == {"Node2D": 1, "Timer": 1, "Node": 1})
    H.check("deepest of the middle", u.deepest(d) == 1)
    root.free()
    H.finish(self)
