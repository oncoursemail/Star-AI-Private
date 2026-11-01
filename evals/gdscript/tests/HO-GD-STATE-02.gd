extends SceneTree
## HO-GD-STATE-02: Health component with clamping setters, change signal and a one-shot died signal. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var h = S.new()
    var changes := []
    var deaths := [0]
    h.changed.connect(func(v): changes.append(v))
    h.died.connect(func(): deaths[0] += 1)
    H.check("starts full", h.hp == 100 and h.max_hp == 100)
    h.damage(30)
    H.check("damage", h.hp == 70 and changes == [70])
    h.hp = 500
    H.check("assigning hp clamps to max", h.hp == 100 and changes == [70, 100])
    h.heal(10)
    H.check("healing at full changes nothing", h.hp == 100 and changes.size() == 2)
    h.damage(-5)
    H.check("negative damage ignored", h.hp == 100 and changes.size() == 2)
    h.max_hp = 60
    H.check("lowering max clamps hp", h.hp == 60 and changes[-1] == 60)
    h.damage(1000)
    H.check("dies at zero, once", h.hp == 0 and h.is_dead() and deaths[0] == 1)
    h.damage(5)
    h.hp = -3
    H.check("no second death while dead", deaths[0] == 1 and h.hp == 0)
    h.heal(20)
    H.check("heal revives", h.hp == 20 and not h.is_dead())
    h.damage(20)
    H.check("can die again", deaths[0] == 2 and h.is_dead())
    h.heal(-4)
    H.check("negative heal ignored", h.hp == 0)
    H.finish(self)
