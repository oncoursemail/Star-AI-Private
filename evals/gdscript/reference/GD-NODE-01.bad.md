Here is the script.

```gdscript
extends RefCounted

func count_by_class(root: Node) -> Dictionary:
    var counts := {}
    for child in root.get_children():
        var key := child.get_class()
        counts[key] = counts.get(key, 0) + 1
    return counts

func deepest(root: Node) -> int:
    if root.get_child_count() > 0:
        return 1
    return 0
```
