Here is the script.

```gdscript
extends RefCounted

signal changed(old_value: int, new_value: int)

var value: int = 0
var _max: int = -1

func _set_value(v: int) -> void:
    var nv := maxi(v, 0)
    if _max >= 0:
        nv = mini(nv, _max)
    if nv == value:
        return
    var old := value
    value = nv
    changed.emit(old, nv)

func increment(by: int = 1) -> void:
    _set_value(value + by)

func reset() -> void:
    _set_value(0)

func set_max(m: int) -> void:
    _max = m
```
