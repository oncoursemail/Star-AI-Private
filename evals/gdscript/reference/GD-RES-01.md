Here is the script.

```gdscript
extends Resource

@export var display_name: String = ""
@export var price: int = 0
@export var tags: PackedStringArray = PackedStringArray()

func to_json() -> String:
    return JSON.stringify({"name": display_name, "price": price, "tags": Array(tags)})

static func from_json(text: String):
    var data = JSON.parse_string(text)
    if not (data is Dictionary):
        return null
    if not (data.get("name") is String):
        return null
    var p = data.get("price")
    if not (p is int or p is float) or p != floorf(p):
        return null
    var item = new()
    item.display_name = data["name"]
    item.price = int(p)
    var t = data.get("tags", [])
    if t is Array:
        for s in t:
            item.tags.append(str(s))
    return item
```
