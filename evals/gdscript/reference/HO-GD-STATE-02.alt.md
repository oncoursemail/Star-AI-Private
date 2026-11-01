Here is the script.

```gdscript
extends RefCounted

signal changed(new_hp: int)
signal died

@export var max_hp: int = 100: set = _set_max_hp
var hp: int = 100: set = _set_hp

func _set_max_hp(value: int) -> void:
    max_hp = max(1, value)
    if hp > max_hp:
        _set_hp(max_hp)

func _set_hp(value: int) -> void:
    var clamped: int = clamp(value, 0, max_hp)
    if clamped == hp:
        return
    var was_alive := hp > 0
    hp = clamped
    changed.emit(hp)
    if was_alive and hp == 0:
        died.emit()

func damage(n: int) -> void:
    if n >= 0:
        _set_hp(hp - n)

func heal(n: int) -> void:
    if n >= 0:
        _set_hp(hp + n)

func is_dead() -> bool:
    return hp <= 0
```
