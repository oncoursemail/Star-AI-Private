Here is the script.

```gdscript
extends Node

signal ready_again

@export var duration: float = 1.0

var _busy := false
var _ends_at := 0.0

func try_use() -> bool:
    if _busy:
        return false
    _busy = true
    _ends_at = Time.get_ticks_msec() / 1000.0 + duration
    get_tree().create_timer(duration).timeout.connect(_finish)
    return true

func _finish() -> void:
    _busy = false
    ready_again.emit()

func is_ready() -> bool:
    return not _busy

func remaining() -> float:
    if not _busy:
        return 0.0
    return maxf(_ends_at - Time.get_ticks_msec() / 1000.0, 0.0)
```
