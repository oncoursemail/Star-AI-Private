Here is the script.

```gdscript
extends RefCounted

signal changed(new_hp: int)
signal died

@export var max_hp: int = 100:
    set(v):
        max_hp = maxi(v, 1)
        if hp > max_hp:
            hp = max_hp

var hp: int = 100:
    set(v):
        var nv := clampi(v, 0, max_hp)
        if nv == hp:
            return
        hp = nv
        changed.emit(hp)
        if hp == 0:
            died.emit()

func damage(n: int) -> void:
    if n > 0:
        hp -= n

func heal(n: int) -> void:
    if n > 0:
        hp += n

func is_dead() -> bool:
    return hp == 0
```
