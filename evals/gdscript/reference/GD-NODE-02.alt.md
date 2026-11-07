Here is the script.

```gdscript
extends Node

var _next := 0

func spawn(n: int) -> void:
    for i in range(n):
        var e := Node2D.new()
        e.name = "Enemy" + str(_next)
        e.position = Vector2(50.0 * _next, 0.0)
        add_child(e)
        e.add_to_group("enemies")
        _next += 1

func kill_all() -> void:
    for e in get_tree().get_nodes_in_group("enemies"):
        if e.get_parent() == self and not e.is_queued_for_deletion():
            e.queue_free()
```
