Here is the script.

```gdscript
extends Node2D

signal expired

var velocity: Vector2 = Vector2.ZERO
var gravity: float = 980.0
var lifetime: float = 2.0

func _physics_process(delta: float) -> void:
    position += velocity * delta
    velocity.y += gravity * delta
    lifetime -= delta
    if lifetime <= 0.0:
        emit_signal("expired")
        queue_free()
```
