Here is the script.

```gdscript
extends RefCounted

func count_by_class(root: Node) -> Dictionary:
    var counts := {}
    var stack: Array[Node] = [root]
    while not stack.is_empty():
        var n: Node = stack.pop_back()
        var key := n.get_class()
        counts[key] = int(counts.get(key, 0)) + 1
        for child in n.get_children():
            stack.append(child)
    return counts

func deepest(root: Node) -> int:
    var best := 0
    for child in root.get_children():
        best = maxi(best, 1 + deepest(child))
    return best
```
