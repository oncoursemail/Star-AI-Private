Here is the script.

```gdscript
extends RefCounted

func setup_actions() -> void:
    InputMap.add_action("move_left")
    var a := InputEventKey.new()
    a.scancode = KEY_A
    InputMap.action_add_event("move_left", a)
    InputMap.add_action("move_right")
    var d := InputEventKey.new()
    d.scancode = KEY_D
    InputMap.action_add_event("move_right", d)
    InputMap.add_action("jump")

func horizontal() -> float:
    return Input.get_action_strength("move_right") - Input.get_action_strength("move_left")
```
