Here is the script.

```gdscript
extends Resource

@export var display_name: String = ""
@export var price: int = 0
@export var tags: PackedStringArray = PackedStringArray()

func to_json() -> String:
    return JSON.stringify({"name": display_name, "price": price, "tags": tags})

static func from_json(text: String):
    var data = JSON.parse_string(text)
    var item = new()
    item.display_name = data["name"]
    item.price = int(data["price"])
    item.tags = PackedStringArray(data.get("tags", []))
    return item
```
