Here is the script.

```gdscript
extends RefCounted

var _items := {}

func add(item: String, qty: int = 1) -> void:
    _items[item] = _items.get(item, 0) + qty

func remove(item: String, qty: int = 1) -> bool:
    if _items.get(item, 0) < qty:
        return false
    _items[item] -= qty
    return true

func count(item: String) -> int:
    return _items.get(item, 0)

func total() -> int:
    var sum := 0
    for n in _items.values():
        sum += n
    return sum

func names() -> Array[String]:
    var out: Array[String] = []
    for k in _items.keys():
        out.append(k)
    return out
```
