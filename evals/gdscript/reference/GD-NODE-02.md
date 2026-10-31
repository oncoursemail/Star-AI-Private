Here is the script.

```gdscript
extends Node

var _spawned := 0

func spawn(n: int) -> void:
    for i in n:
        var enemy := Node2D.new()
        enemy.name = "Enemy%d" % _spawned
        enemy.position = Vector2(50 * _spawned, 0)
        enemy.add_to_group("enemies")
        add_child(enemy)
        _spawned += 1

func kill_all() -> void:
    for child in get_children():
        if child.is_in_group("enemies"):
            child.queue_free()
```
