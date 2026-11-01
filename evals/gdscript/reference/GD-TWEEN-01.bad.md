Here is the script.

```gdscript
extends Node

func fade_out(node: CanvasItem, duration: float) -> Tween:
    var tween := create_tween()
    tween.tween_property(node, "modulate:a", 0.0, duration)
    return tween
```
