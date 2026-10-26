Here is the script.

```gdscript
extends RefCounted

const BINDINGS := {
    "move_left": [KEY_A, KEY_LEFT],
    "move_right": [KEY_D, KEY_RIGHT],
    "jump": [KEY_SPACE],
}

func setup_actions() -> void:
    for action in BINDINGS:
        if InputMap.has_action(action):
            continue
        InputMap.add_action(action)
        for key in BINDINGS[action]:
            var event := InputEventKey.new()
            event.keycode = key
            InputMap.action_add_event(action, event)

func horizontal() -> float:
    return Input.get_axis("move_left", "move_right")
```
