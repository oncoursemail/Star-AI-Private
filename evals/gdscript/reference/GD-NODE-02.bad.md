Here is the script.

```gdscript
extends Node

func spawn(n: int) -> void:
    for i in n:
        var enemy := Node2D.new()
        enemy.name = "Enemy" + str(i)
        enemy.position = Vector2(50 * i, 0)
        add_child(enemy)

func kill_all() -> void:
    for child in get_children():
        child.queue_free()
```
