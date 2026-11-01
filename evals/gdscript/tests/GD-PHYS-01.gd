extends SceneTree
## GD-PHYS-01: Per-physics-step integration order, one-shot expiry signal. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var p = S.new()
    p.velocity = Vector2(100, 0)
    p.gravity = 10.0
    p.lifetime = 0.25
    var fired := [0]
    p.expired.connect(func(): fired[0] += 1)
    p._physics_process(0.1)
    H.check("velocity gets gravity first", p.velocity.is_equal_approx(Vector2(100, 1.0)))
    H.check("position uses the new velocity", p.position.is_equal_approx(Vector2(10, 0.1)))
    H.check("not expired yet", fired[0] == 0)
    p._physics_process(0.1)
    H.check("still alive at 0.05 left", fired[0] == 0)
    p._physics_process(0.1)
    H.check("expired once when lifetime runs out", fired[0] == 1)
    p._physics_process(0.1)
    H.check("no second expiry", fired[0] == 1)
    p.free()
    H.finish(self)
