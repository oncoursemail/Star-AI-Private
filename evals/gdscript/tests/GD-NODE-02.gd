extends SceneTree
## GD-NODE-02: Spawner that names nodes, joins a group and frees them deferred. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var sp = S.new()
    root.add_child(sp)
    sp.spawn(3)
    H.check("three children", sp.get_child_count() == 3)
    H.check("names", str(sp.get_child(0).name) == "Enemy0" and str(sp.get_child(2).name) == "Enemy2")
    H.check("positions", sp.get_child(2).position == Vector2(100, 0) and sp.get_child(1).position == Vector2(50, 0))
    H.check("in the group", get_nodes_in_group("enemies").size() == 3)
    sp.spawn(0)
    sp.spawn(2)
    H.check("numbering continues", sp.get_child_count() == 5 and sp.has_node("Enemy4") and sp.get_node("Enemy3").position == Vector2(150, 0))
    sp.kill_all()
    sp.kill_all()
    await process_frame
    H.check("everything is gone after a frame", get_nodes_in_group("enemies").size() == 0 and sp.get_child_count() == 0)
    sp.spawn(1)
    H.check("numbering is not reset by kill_all", sp.has_node("Enemy5"))
    H.finish(self)
