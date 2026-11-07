Here is the script.

```gdscript
extends RefCounted

signal changed(new_hp: int)
signal died

@export var max_hp: int = 100
var hp: int = 100

func damage(n: int) -> void:
    hp = max(hp - n, 0)
    emit_signal("changed", hp)
    if hp == 0:
        emit_signal("died")

func heal(n: int) -> void:
    hp = min(hp + n, max_hp)
    emit_signal("changed", hp)

func is_dead() -> bool:
    return hp <= 0
```
