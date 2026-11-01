extends SceneTree
## GD-INPUT-01: Register InputMap actions in code, idempotently, and read an axis. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var g = S.new()
    g.setup_actions()
    g.setup_actions()
    H.check("actions exist", InputMap.has_action("move_left") and InputMap.has_action("move_right") and InputMap.has_action("jump"))
    var left: Array = InputMap.action_get_events("move_left")
    var keys: Array = []
    for ev in left:
        if ev is InputEventKey:
            keys.append(ev.keycode if ev.keycode != KEY_NONE else ev.physical_keycode)
    keys.sort()
    var want: Array = [KEY_A, KEY_LEFT]
    want.sort()
    H.check("move_left has A and Left, once each", keys == want)
    H.check("jump has exactly one event, Space", InputMap.action_get_events("jump").size() == 1 and (InputMap.action_get_events("jump")[0].keycode == KEY_SPACE or InputMap.action_get_events("jump")[0].physical_keycode == KEY_SPACE))
    H.check("move_right has two events", InputMap.action_get_events("move_right").size() == 2)
    H.check("axis at rest", g.horizontal() == 0.0)
    Input.action_press("move_right")
    H.check("axis right", is_equal_approx(g.horizontal(), 1.0))
    Input.action_press("move_left")
    H.check("both cancel", is_equal_approx(g.horizontal(), 0.0))
    Input.action_release("move_right")
    H.check("axis left", is_equal_approx(g.horizontal(), -1.0))
    Input.action_release("move_left")
    H.finish(self)
