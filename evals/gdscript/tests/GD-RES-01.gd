extends SceneTree
## GD-RES-01: Custom Resource with exports and a validating static JSON factory. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var a = S.new()
    a.display_name = "Torch"
    a.price = 12
    a.tags = PackedStringArray(["light", "wood"])
    var text: String = a.to_json()
    var parsed = JSON.parse_string(text)
    H.check("json carries name and price", parsed is Dictionary and parsed.get("name") == "Torch" and int(parsed.get("price", -1)) == 12)
    H.check("tags are a plain array", parsed is Dictionary and parsed.get("tags") is Array and parsed["tags"] == ["light", "wood"])
    var b = S.from_json(text)
    H.check("round trip", b != null and b.display_name == "Torch" and b.price == 12 and Array(b.tags) == ["light", "wood"])
    H.check("same script, new instance", b != null and b.get_script() == S and b != a)
    H.check("invalid json", S.from_json("{nope") == null)
    H.check("not an object", S.from_json("[1, 2]") == null)
    H.check("missing name", S.from_json('{"price": 3}') == null)
    H.check("fractional price", S.from_json('{"name": "x", "price": 2.5}') == null)
    H.check("name must be a string", S.from_json('{"name": 4, "price": 2}') == null)
    var c = S.from_json('{"name": "x", "price": 4.0}')
    H.check("missing tags allowed", c != null and c.price == 4 and c.tags.size() == 0)
    H.finish(self)
