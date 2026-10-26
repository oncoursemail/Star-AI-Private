extends SceneTree
## HO-GD-SIG-02: Cooldown node timed through the scene tree, with one ready signal per cycle. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var c = S.new()
    c.duration = 0.12
    root.add_child(c)
    var fired := [0]
    c.ready_again.connect(func(): fired[0] += 1)
    H.check("starts ready", c.is_ready() and c.remaining() == 0.0)
    H.check("first use works", c.try_use() == true)
    H.check("busy now", c.is_ready() == false and c.try_use() == false)
    H.check("remaining is within the duration", c.remaining() > 0.0 and c.remaining() <= 0.121)
    await create_timer(0.35).timeout
    H.check("ready again exactly once", c.is_ready() and fired[0] == 1 and c.remaining() == 0.0)
    H.check("usable again", c.try_use() == true)
    await create_timer(0.35).timeout
    H.check("second cycle fires once more", fired[0] == 2)
    H.finish(self)
