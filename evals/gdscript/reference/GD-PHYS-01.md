Here is the script.

```gdscript
extends Node2D

signal expired

var velocity: Vector2 = Vector2.ZERO
var gravity: float = 980.0
var lifetime: float = 2.0
var _expired := false

func _physics_process(delta: float) -> void:
    velocity.y += gravity * delta
    position += velocity * delta
    lifetime -= delta
    if lifetime <= 0.0 and not _expired:
        _expired = true
        expired.emit()
        queue_free()
```
