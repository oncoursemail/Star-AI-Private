Here is the script.

```gdscript
extends RefCounted

signal changed(old_value: int, new_value: int)

var value: int = 0
var max_value: int = 1000000

func increment(by: int = 1) -> void:
    var old := value
    value = clampi(value + by, 0, max_value)
    emit_signal("changed", old, value)

func reset() -> void:
    var old := value
    value = 0
    emit_signal("changed", old, value)

func set_max(m: int) -> void:
    max_value = m
    value = mini(value, m)
```
