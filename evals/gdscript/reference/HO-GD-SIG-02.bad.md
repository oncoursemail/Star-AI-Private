Here is the script.

```gdscript
extends Node

signal ready_again

@export var duration: float = 1.0

var ready := true

func try_use() -> bool:
    ready = false
    yield(get_tree().create_timer(duration), "timeout")
    ready = true
    emit_signal("ready_again")
    return true

func is_ready() -> bool:
    return ready

func remaining() -> float:
    return 0.0
```
