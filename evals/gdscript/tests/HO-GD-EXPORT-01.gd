extends SceneTree
## HO-GD-EXPORT-01: Godot 4 export annotations: range, enum, flags, multiline, group, and a private variable. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var plist: Array = S.get_script_property_list()
    var by_name := {}
    var order: Array = []
    for p in plist:
        by_name[p["name"]] = p
        order.append(p["name"])
    var inst = S.new()
    H.check("defaults", inst.speed == 100.0 and inst.mode == 0 and inst.resist == 0 and inst.notes == "" and inst.label == "unit" and inst.damage == 5)
    var rng := str(by_name["speed"]["hint_string"]).split(",") if by_name.has("speed") else PackedStringArray()
    H.check("speed is a range 0..500 step 5", by_name.has("speed") and by_name["speed"]["hint"] == PROPERTY_HINT_RANGE and rng.size() >= 3 and float(rng[0]) == 0.0 and float(rng[1]) == 500.0 and float(rng[2]) == 5.0)
    H.check("mode is an enum", by_name.has("mode") and by_name["mode"]["hint"] == PROPERTY_HINT_ENUM and str(by_name["mode"]["hint_string"]).replace(" ", "") == "Idle,Walk,Run")
    H.check("resist is flags", by_name.has("resist") and by_name["resist"]["hint"] == PROPERTY_HINT_FLAGS and str(by_name["resist"]["hint_string"]).replace(" ", "") == "Fire,Ice,Wind")
    H.check("notes is multiline", by_name.has("notes") and by_name["notes"]["hint"] == PROPERTY_HINT_MULTILINE_TEXT)
    H.check("label and damage are inspector properties", by_name.has("label") and (by_name["label"]["usage"] & PROPERTY_USAGE_EDITOR) != 0 and by_name.has("damage") and (by_name["damage"]["usage"] & PROPERTY_USAGE_EDITOR) != 0)
    H.check("the private cache is not exported", not by_name.has("_cache") or (by_name["_cache"]["usage"] & PROPERTY_USAGE_EDITOR) == 0)
    var group_at: int = order.find("Combat")
    H.check("group Combat comes right before damage", group_at >= 0 and (by_name["Combat"]["usage"] & PROPERTY_USAGE_GROUP) != 0 and order.find("damage") > group_at and order.find("label") < group_at)
    inst.free()
    H.finish(self)
