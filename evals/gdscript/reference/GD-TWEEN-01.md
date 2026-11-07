Here is the script.

```gdscript
extends Node

func fade_out(node: CanvasItem, duration: float) -> Tween:
    var tween := node.create_tween()
    tween.tween_property(node, "modulate:a", 0.0, duration)
    tween.tween_callback(node.queue_free)
    return tween
```
