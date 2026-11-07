Here is the script.

```gdscript
extends RefCounted

func _add(action: String, keycodes: Array) -> void:
    if InputMap.has_action(action):
        return
    InputMap.add_action(action)
    for code in keycodes:
        var ev := InputEventKey.new()
        ev.physical_keycode = code
        InputMap.action_add_event(action, ev)

func setup_actions() -> void:
    _add("move_left", [KEY_A, KEY_LEFT])
    _add("move_right", [KEY_D, KEY_RIGHT])
    _add("jump", [KEY_SPACE])

func horizontal() -> float:
    return Input.get_axis("move_left", "move_right")
```
