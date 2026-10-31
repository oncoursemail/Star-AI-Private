extends SceneTree
## GD-MATH-01: Capped movement step, angle wrapping and unsigned angle between vectors. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var m = S.new()
    H.check("partway", m.step_toward(Vector2(0, 0), Vector2(10, 0), 2.0, 1.0).is_equal_approx(Vector2(2, 0)))
    H.check("diagonal", m.step_toward(Vector2(0, 0), Vector2(3, 4), 5.0, 0.5).is_equal_approx(Vector2(1.5, 2.0)))
    H.check("no overshoot", m.step_toward(Vector2(0, 0), Vector2(1, 0), 5.0, 1.0).is_equal_approx(Vector2(1, 0)))
    H.check("already there", m.step_toward(Vector2(4, 4), Vector2(4, 4), 3.0, 1.0).is_equal_approx(Vector2(4, 4)))
    H.check("wrap 1.5 PI", absf(m.wrap_angle(1.5 * PI) - (-0.5 * PI)) < 0.0001)
    H.check("wrap -1.5 PI", absf(m.wrap_angle(-1.5 * PI) - (0.5 * PI)) < 0.0001)
    H.check("wrap leaves small angles", absf(m.wrap_angle(0.25) - 0.25) < 0.0001 and absf(m.wrap_angle(7.0) - (7.0 - TAU)) < 0.0001)
    H.check("right angle", absf(m.angle_between_deg(Vector2(1, 0), Vector2(0, 1)) - 90.0) < 0.001)
    H.check("opposite and equal", absf(m.angle_between_deg(Vector2(1, 0), Vector2(-3, 0)) - 180.0) < 0.001 and absf(m.angle_between_deg(Vector2(1, 0), Vector2(2, 0))) < 0.001)
    H.check("unsigned and zero vector", absf(m.angle_between_deg(Vector2(0, 1), Vector2(1, 0)) - 90.0) < 0.001 and m.angle_between_deg(Vector2.ZERO, Vector2(1, 0)) == 0.0)
    H.finish(self)
