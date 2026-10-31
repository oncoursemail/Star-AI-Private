Here is the script.

```gdscript
extends RefCounted

var _items: Dictionary = {}

func add(item: String, qty: int = 1) -> void:
    if qty <= 0:
        return
    _items[item] = int(_items.get(item, 0)) + qty

func remove(item: String, qty: int = 1) -> bool:
    if qty <= 0 or int(_items.get(item, 0)) < qty:
        return false
    var left: int = int(_items[item]) - qty
    if left == 0:
        _items.erase(item)
    else:
        _items[item] = left
    return true

func count(item: String) -> int:
    return int(_items.get(item, 0))

func total() -> int:
    var sum := 0
    for n in _items.values():
        sum += int(n)
    return sum

func names() -> Array[String]:
    var out: Array[String] = []
    for k in _items.keys():
        out.append(k)
    out.sort()
    return out
```
