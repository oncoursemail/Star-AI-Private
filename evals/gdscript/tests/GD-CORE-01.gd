extends SceneTree
## GD-CORE-01: Stackable inventory with guarded add/remove and sorted names. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var inv = S.new()
    inv.add("rope")
    inv.add("rope", 2)
    inv.add("axe", 1)
    inv.add("ghost", 0)
    inv.add("ghost", -3)
    H.check("counts after adds", inv.count("rope") == 3 and inv.count("axe") == 1)
    H.check("non-positive qty ignored", inv.count("ghost") == 0 and inv.total() == 4)
    H.check("removing too many fails and changes nothing", inv.remove("rope", 5) == false and inv.count("rope") == 3)
    H.check("remove works", inv.remove("rope", 2) == true and inv.count("rope") == 1)
    H.check("count zero drops the entry", inv.remove("axe") == true and not Array(inv.names()).has("axe"))
    H.check("unknown item", inv.remove("nothing") == false)
    inv.add("zeta")
    inv.add("beta")
    H.check("names sorted", Array(inv.names()) == ["beta", "rope", "zeta"])
    H.check("zero qty remove rejected", inv.remove("rope", 0) == false and inv.count("rope") == 1)
    H.finish(self)
