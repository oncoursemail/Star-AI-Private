Here is the script.

```gdscript
extends Node

func fade_out(node: CanvasItem, duration: float) -> Tween:
    var tw: Tween = get_tree().create_tween()
    tw.tween_property(node, "modulate:a", 0.0, duration).set_trans(Tween.TRANS_LINEAR)
    tw.finished.connect(func():
        if is_instance_valid(node):
            node.queue_free())
    return tw
```
