Here is the script.

```gdscript
extends Node

signal ready_again

@export var duration: float = 1.0

var _timer: Timer

func _ready() -> void:
    _timer = Timer.new()
    _timer.one_shot = true
    add_child(_timer)
    _timer.timeout.connect(func(): ready_again.emit())

func try_use() -> bool:
    if not _timer.is_stopped():
        return false
    _timer.start(duration)
    return true

func is_ready() -> bool:
    return _timer.is_stopped()

func remaining() -> float:
    return _timer.time_left
```
