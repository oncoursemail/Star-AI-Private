Here is the script.

```gdscript
extends RefCounted

var stock: Dictionary[String, int] = {}

func add(item: String, qty: int = 1) -> void:
    if qty > 0:
        stock[item] = stock.get(item, 0) + qty

func remove(item: String, qty: int = 1) -> bool:
    if qty <= 0 or not stock.has(item) or stock[item] < qty:
        return false
    stock[item] -= qty
    if stock[item] == 0:
        stock.erase(item)
    return true

func count(item: String) -> int:
    return stock.get(item, 0)

func total() -> int:
    var t := 0
    for v in stock.values():
        t += v
    return t

func names() -> Array[String]:
    var keys: Array[String] = stock.keys()
    keys.sort()
    return keys
```
