extends SceneTree
## GD-TWEEN-01: Tween fade that frees the node when finished and returns the Tween. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var n := ColorRect.new()
    var other := ColorRect.new()
    root.add_child(n)
    root.add_child(other)
    var f = S.new()
    root.add_child(f)
    var tw = f.fade_out(n, 0.2)
    H.check("returns a Tween", tw is Tween)
    H.check("the tween is running", tw is Tween and tw.is_running())
    await create_timer(0.08).timeout
    H.check("halfway: alive and partly transparent", is_instance_valid(n) and n.modulate.a < 0.95 and n.modulate.a > 0.05)
    await create_timer(0.4).timeout
    H.check("freed after the tween", not is_instance_valid(n))
    H.check("other nodes are untouched", is_instance_valid(other) and other.modulate.a == 1.0)
    H.finish(self)
